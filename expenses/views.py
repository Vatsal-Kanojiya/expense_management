from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.db.models.deletion import ProtectedError
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView

from .filters import DateRangeForm, ExpenseFilterForm
from .forms import CategoryForm, ExpenseForm
from .mixins import OwnerFormMixin, OwnerScopedMixin
from .models import Category, Expense
from .summaries import previous_period, summarise


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
        return super().get_queryset().annotate(expense_count=Count("expenses"))


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
        queryset = super().get_queryset().select_related("category")
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


class ExpenseCreateView(OwnerScopedMixin, OwnerFormMixin, CreateView):
    model = Expense
    form_class = ExpenseForm
    success_url = reverse_lazy("expenses:expense_list")

    def form_valid(self, form):
        messages.success(self.request, "Expense added.")
        return super().form_valid(form)


class ExpenseUpdateView(OwnerScopedMixin, OwnerFormMixin, UpdateView):
    model = Expense
    form_class = ExpenseForm
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
