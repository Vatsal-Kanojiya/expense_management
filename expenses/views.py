from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
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

from .balances import balances
from .filters import DateRangeForm, ExpenseFilterForm
from .forms import CategoryForm, ExpenseForm, ExpenseItemFormSet, ParticipantForm
from .mixins import ItemFormSetMixin, OwnerFormMixin, OwnerScopedMixin
from .models import Category, Expense, ExpenseItem, ExportJob, Participant
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

        current = summarise(self.request.user, start, end)
        previous = summarise(self.request.user, *previous_period(start, end))

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
        owed = balances(self.request.user, start, end)

        context.update(
            form=form,
            start=start,
            end=end,
            balances=owed,
            total=sum((amount for _, amount in owed), Decimal("0")),
        )
        return context


class ParticipantListView(OwnerScopedMixin, ListView):
    model = Participant
    context_object_name = "participants"

    def get_queryset(self):
        # Two counts in one query. Counting across two different relations in
        # a single annotate() would multiply the join and inflate both, so
        # each uses distinct=True.
        return (
            super()
            .get_queryset()
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

    def form_valid(self, form):
        messages.success(self.request, f"Renamed to {form.instance.name}.")
        return super().form_valid(form)


class ParticipantDeleteView(OwnerScopedMixin, DeleteView):
    model = Participant
    success_url = reverse_lazy("expenses:participant_list")

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
        # select_related joins the category in the same query. Without it the
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
            .select_related("category")
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
