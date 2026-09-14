from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, OuterRef, Prefetch, Subquery, Sum
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, Http404
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from .balances import balances, outstanding_balances, split_expense
from .cache import cached_summary, owed_count_key
from .filters import DateRangeForm, ExpenseFilterForm
from .forms import CategoryForm, ExpenseForm, ExpenseItemFormSet, ParticipantForm
from .mixins import ItemFormSetMixin, OwnerFormMixin, OwnerScopedMixin
from .models import Category, Expense, ExpenseItem, ExportJob, Participant
from .settlements import settle_up
from .summaries import previous_period, summarise
from .tasks import build_expense_export


class DashboardView(LoginRequiredMixin, TemplateView):
    """Spending summary for a date range, defaulting to the current month.

    A TemplateView rather than a ListView: the page is aggregates, not a
    list of objects. Forcing it into ListView would mean a queryset that
    exists only to be ignored.

    No OwnerScopedMixin here because there is no queryset to scope — the
    scoping happens inside summarise(), which is called with request.user.
    """

    template_name = "expenses/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        form = DateRangeForm(self.request.GET or None)
        start, end = form.range_or_default()

        user = self.request.user
        previous_start, previous_end = previous_period(start, end)

        # The aggregation is three queries over every expense in the range,
        # run on every page view, and it changes only when the user writes.
        current = cached_summary(user, start, end, lambda: summarise(user, start, end))
        previous = cached_summary(
            user,
            previous_start,
            previous_end,
            lambda: summarise(user, previous_start, previous_end),
        )

        context.update(
            form=form,
            summary=current,
            previous=previous,
            change=current.change_from(previous),
        )
        return context


class CategoryListView(OwnerScopedMixin, ListView):
    model = Category
    context_object_name = "categories"

    def get_queryset(self):
        # The latest expense in each category, as a correlated subquery.
        #
        # An aggregate cannot do this. Max("expenses__spent_on") gives the
        # latest *date*, but there is no aggregate that returns the amount
        # belonging to that same row -- Max on both columns would happily
        # pair the newest date with the largest amount from a different
        # expense. Subquery selects one row and reads fields off it.
        #
        # OuterRef("pk") is the correlation: it resolves to the category
        # row being annotated, which is why this cannot be evaluated on its
        # own and only means anything inside annotate().
        latest = Expense.objects.filter(category=OuterRef("pk")).order_by("-spent_on", "-id")

        return (
            super()
            .get_queryset()
            .annotate(
                expense_count=Count("expenses"),
                total=Sum("expenses__amount"),
                last_spent_on=Subquery(latest.values("spent_on")[:1]),
                last_amount=Subquery(latest.values("amount")[:1]),
            )
        )


class CategoryCreateView(OwnerScopedMixin, OwnerFormMixin, CreateView):
    model = Category
    form_class = CategoryForm
    success_url = reverse_lazy("expenses:category_list")

    def form_valid(self, form):
        messages.success(self.request, f"Category “{form.instance.name}” created.")
        return super().form_valid(form)


class CategoryUpdateView(OwnerScopedMixin, OwnerFormMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    success_url = reverse_lazy("expenses:category_list")

    def form_valid(self, form):
        messages.success(self.request, f"Category “{form.instance.name}” updated.")
        return super().form_valid(form)


class CategoryDeleteView(OwnerScopedMixin, DeleteView):
    model = Category
    success_url = reverse_lazy("expenses:category_list")

    def form_valid(self, form):
        # Expense.category is on_delete=PROTECT, so deleting a category that
        # still has expenses raises rather than silently destroying history.
        # Turn that into a message instead of a 500.
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(
                self.request,
                f"“{self.object.name}” still has expenses, so it cannot be deleted. "
                "Reassign or delete those expenses first.",
            )
            return redirect(self.success_url)

        messages.success(self.request, f"Category “{self.object.name}” deleted.")
        return response


class BalanceView(LoginRequiredMixin, TemplateView):
    """Who owes you, over a date range.

    A TemplateView for the same reason as the dashboard: the page is derived
    numbers, not a list of rows. Scoping happens inside balances(), which is
    called with request.user, so there is no queryset for OwnerScopedMixin
    to narrow.
    """

    template_name = "expenses/balances.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        form = DateRangeForm(self.request.GET or None)
        start, end = form.range_or_default()
        gross = balances(self.request.user, start, end)
        net = outstanding_balances(self.request.user, start, end)

        # Populate the nav badge while the number is in hand. The context
        # processor only ever reads this, so if nobody visits this page the
        # badge is simply absent rather than expensive.
        cache.set(owed_count_key(self.request.user.pk), len(net), 300)

        context.update(
            form=form,
            start=start,
            end=end,
            balances=net,
            gross=dict(gross),
            total=sum((amount for _, amount in net), Decimal("0")),
        )
        return context


class SettleUpView(LoginRequiredMixin, View):
    """Record that a participant has repaid what they owe.

    POST only. A GET that writes could be triggered by a link prefetch or
    an <img> tag, and this one writes money.
    """

    def post(self, request, pk, *args, **kwargs):
        try:
            settlement = settle_up(request.user, pk)
        except Participant.DoesNotExist as exc:
            # Someone else's participant is a 404, matching every other
            # detail-bound view rather than confirming the row exists.
            raise Http404("No such person.") from exc

        if settlement is None:
            messages.info(request, "Nothing outstanding.")
        else:
            messages.success(
                request, f"Recorded {settlement.amount} back from {settlement.participant}."
            )

        return redirect("expenses:balances")


class ParticipantListView(OwnerScopedMixin, ListView):
    model = Participant
    context_object_name = "participants"

    def get_queryset(self):
        # Two counts in one query. Counting across two different relations in
        # a single annotate() would multiply the join and inflate both, so
        # each uses distinct=True.
        # Self ("You") is excluded: it is a split participant, not an address-book contact.
        return (
            super()
            .get_queryset()
            .filter(is_self=False)
            .annotate(
                shared_count=Count("shared_expenses", distinct=True),
                item_count=Count("item_shares", distinct=True),
            )
        )


class ParticipantCreateView(OwnerScopedMixin, OwnerFormMixin, CreateView):
    model = Participant
    form_class = ParticipantForm
    success_url = reverse_lazy("expenses:participant_list")

    def form_valid(self, form):
        messages.success(self.request, f"Added {form.instance.name}.")
        return super().form_valid(form)


class ParticipantUpdateView(OwnerScopedMixin, OwnerFormMixin, UpdateView):
    model = Participant
    form_class = ParticipantForm
    success_url = reverse_lazy("expenses:participant_list")

    def get_queryset(self):
        return super().get_queryset().filter(is_self=False)

    def form_valid(self, form):
        messages.success(self.request, f"Renamed to {form.instance.name}.")
        return super().form_valid(form)


class ParticipantDeleteView(OwnerScopedMixin, DeleteView):
    model = Participant
    success_url = reverse_lazy("expenses:participant_list")

    def get_queryset(self):
        return super().get_queryset().filter(is_self=False)

    def form_valid(self, form):
        # ItemShare.participant is PROTECT, so someone who appears on a line
        # item cannot be removed — deleting them would leave that item
        # charged to nobody. Even-split rows do NOT protect: that join table
        # is generated by Django and hard-codes CASCADE.
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(
                self.request,
                f"{self.object.name} is on the items of at least one expense, "
                "so they cannot be removed. Delete or re-share those items first.",
            )
            return redirect(self.success_url)

        messages.success(self.request, f"Removed {self.object.name}.")
        return response


class ExpenseListView(OwnerScopedMixin, ListView):
    model = Expense
    context_object_name = "expenses"
    paginate_by = 25

    def get_filter_form(self):
        # Built once and reused, so the queryset and the rendered form
        # cannot disagree about what was filtered.
        if not hasattr(self, "_filter_form"):
            self._filter_form = ExpenseFilterForm(self.request.GET or None, user=self.request.user)
        return self._filter_form

    def get_queryset(self):
        # select_related joins the category and payer in the same query. Without it the
        # template's {{ expense.category.name }} fires one extra query per row
        # — the classic N+1.
        # select_related joins the category into the same query; it is a
        # forward FK, so a JOIN is possible. participants and items are
        # multi-valued, where a JOIN would multiply rows instead, so those
        # need prefetch_related -- one extra query each, not one per row.
        #
        # The nested Prefetch reaches three levels: items, their shares, and
        # each share's participant. Without it, rendering "shared with" on a
        # 25-row page costs 25 queries for items plus one per item for its
        # shares. test_orm.py pins the count so it cannot drift back.
        queryset = (
            super()
            .get_queryset()
            .select_related("category", "paid_by")
            .prefetch_related(
                "participants",
                Prefetch(
                    "items",
                    queryset=ExpenseItem.objects.prefetch_related("shares__participant"),
                ),
            )
        )
        return self.get_filter_form().apply(queryset)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = self.get_filter_form()

        context["form"] = form
        context["is_filtered"] = form.is_filtered()
        # Sum of the filtered set, not just the page, so the number answers
        # "how much did I spend on this" rather than "what is on screen".
        context["filtered_total"] = self.get_queryset().total()
        return context


class ExpenseCreateView(OwnerScopedMixin, ItemFormSetMixin, OwnerFormMixin, CreateView):
    model = Expense
    form_class = ExpenseForm
    formset_class = ExpenseItemFormSet
    success_url = reverse_lazy("expenses:expense_list")

    def form_valid(self, form):
        # ItemFormSetMixin sits between this and OwnerFormMixin in the MRO,
        # so the message is queued before the transaction that writes the
        # items. Django only flushes messages when the response is rendered,
        # so a rollback below still discards it.
        messages.success(self.request, "Expense added.")
        return super().form_valid(form)


class ExpenseUpdateView(OwnerScopedMixin, ItemFormSetMixin, OwnerFormMixin, UpdateView):
    model = Expense
    form_class = ExpenseForm
    formset_class = ExpenseItemFormSet
    success_url = reverse_lazy("expenses:expense_list")

    def get_queryset(self):
        return super().get_queryset().select_related("paid_by").prefetch_related("participants")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        fresh_expense = (
            Expense.objects.for_user(self.request.user)
            .select_related("paid_by")
            .prefetch_related(
                "participants",
                Prefetch(
                    "items",
                    queryset=ExpenseItem.objects.prefetch_related("shares__participant"),
                ),
            )
            .get(pk=self.object.pk)
        )
        rows = split_expense(fresh_expense)
        if rows is not None and any(r.participant is not None for r in rows):
            context["split"] = rows
            context["split_items_total"] = sum((r.items for r in rows), Decimal("0"))
            context["split_misc_total"] = sum((r.misc for r in rows), Decimal("0"))
            context["split_grand_total"] = sum((r.total for r in rows), Decimal("0"))
        else:
            context["split"] = None
        return context

    def form_valid(self, form):
        messages.success(self.request, "Expense updated.")
        return super().form_valid(form)


class ExpenseDeleteView(OwnerScopedMixin, DeleteView):
    model = Expense
    success_url = reverse_lazy("expenses:expense_list")

    def form_valid(self, form):
        messages.success(self.request, "Expense deleted.")
        return super().form_valid(form)


class ExportCreateView(LoginRequiredMixin, View):
    """Queue a CSV export and return immediately.

    This is the case that genuinely needs a task queue. Building the file
    inline would hold the request open for as long as the export takes,
    which is unbounded — it grows with the user's history. The view writes
    one row, dispatches, and redirects; the worker does the slow part.
    """

    def post(self, request, *args, **kwargs):
        form = DateRangeForm(request.POST or None)
        start, end = form.range_or_default()

        job = ExportJob.objects.create(user=request.user, start=start, end=end)

        # transaction.on_commit, not .delay() directly. Dispatching inside
        # an open transaction is a real race: the worker is fast enough to
        # pick the job up and query for a row the web process has not
        # committed yet, and the task fails with DoesNotExist.
        transaction.on_commit(
            lambda: build_expense_export.delay(
                job.pk, site_url=request.build_absolute_uri("/").rstrip("/")
            )
        )

        messages.success(
            request,
            "Export queued. You'll get an email with a download link when it's ready.",
        )
        return redirect("expenses:export_list")


class ExportListView(OwnerScopedMixin, ListView):
    model = ExportJob
    context_object_name = "jobs"
    paginate_by = 20
    template_name = "expenses/export_list.html"


class ExportDownloadView(OwnerScopedMixin, DetailView):
    """Serve a finished export.

    Scoped like every other detail view, so another user's job id is a 404.
    FileResponse is fine in development; in production this should hand off
    to the web server (X-Accel-Redirect) or a signed object-storage URL so
    Python is not streaming bytes.
    """

    model = ExportJob

    def get(self, request, *args, **kwargs):
        job = self.get_object()

        if job.status != ExportJob.Status.COMPLETE or not job.file:
            raise Http404("This export is not ready yet.")

        return FileResponse(
            job.file.open("rb"),
            as_attachment=True,
            filename=f"expenses-{job.start:%Y%m%d}-{job.end:%Y%m%d}.csv",
        )
