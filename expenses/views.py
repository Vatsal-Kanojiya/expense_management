from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.db.models.deletion import ProtectedError
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .forms import CategoryForm, ExpenseForm
from .models import Category, Expense


class CategoryListView(LoginRequiredMixin, ListView):
    model = Category
    context_object_name = "categories"

    def get_queryset(self):
        # The security boundary. Never Category.objects.all() in a view:
        # scoping happens here, once, rather than being trusted to templates.
        return (
            Category.objects.filter(user=self.request.user)
            .annotate(expense_count=Count("expenses"))
        )


class CategoryCreateView(LoginRequiredMixin, CreateView):
    model = Category
    form_class = CategoryForm
    success_url = reverse_lazy("expenses:category_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        # Ownership is assigned server-side from the session, never from
        # posted data.
        form.instance.user = self.request.user
        messages.success(self.request, f"Category “{form.instance.name}” created.")
        return super().form_valid(form)


class CategoryUpdateView(LoginRequiredMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    success_url = reverse_lazy("expenses:category_list")

    def get_queryset(self):
        # Scoping get_queryset is what makes another user's id a 404 rather
        # than an edit form. This is the object-level permission check.
        return Category.objects.filter(user=self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, f"Category “{form.instance.name}” updated.")
        return super().form_valid(form)


class CategoryDeleteView(LoginRequiredMixin, DeleteView):
    model = Category
    success_url = reverse_lazy("expenses:category_list")

    def get_queryset(self):
        return Category.objects.filter(user=self.request.user)

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


class ExpenseListView(LoginRequiredMixin, ListView):
    model = Expense
    context_object_name = "expenses"
    paginate_by = 25

    def get_queryset(self):
        # select_related joins the category in the same query. Without it the
        # template's {{ expense.category.name }} fires one extra query per row
        # — the classic N+1.
        return (
            Expense.objects.filter(user=self.request.user)
            .select_related("category")
        )


class ExpenseCreateView(LoginRequiredMixin, CreateView):
    model = Expense
    form_class = ExpenseForm
    success_url = reverse_lazy("expenses:expense_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.user = self.request.user
        messages.success(self.request, "Expense added.")
        return super().form_valid(form)


class ExpenseUpdateView(LoginRequiredMixin, UpdateView):
    model = Expense
    form_class = ExpenseForm
    success_url = reverse_lazy("expenses:expense_list")

    def get_queryset(self):
        return Expense.objects.filter(user=self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, "Expense updated.")
        return super().form_valid(form)


class ExpenseDeleteView(LoginRequiredMixin, DeleteView):
    model = Expense
    success_url = reverse_lazy("expenses:expense_list")

    def get_queryset(self):
        return Expense.objects.filter(user=self.request.user)

    def form_valid(self, form):
        messages.success(self.request, "Expense deleted.")
        return super().form_valid(form)
