from decimal import Decimal

from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from .models import Category, Expense, ExpenseItem, Participant


class CategoryForm(forms.ModelForm):
    """Form for a user's own categories.

    `user` is deliberately NOT a form field. If it were, the browser could
    post any user id and reassign ownership. Instead the view supplies the
    user out of band and the form uses it only for validation.
    """

    class Meta:
        model = Category
        fields = ["name"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_name(self):
        name = self.cleaned_data["name"].strip()

        # The DB already has UniqueConstraint(user, name) as the backstop, but
        # a ModelForm cannot check it: Django excludes constraints that touch
        # fields absent from the form, and `user` is absent by design. Without
        # this check a duplicate becomes an IntegrityError 500 instead of a
        # field error. Two layers, two jobs: the DB guarantees, the form explains.
        duplicates = Category.objects.filter(user=self.user, name__iexact=name)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError("You already have a category with this name.")

        return name


class ParticipantForm(forms.ModelForm):
    """Someone you split bills with.

    Same shape as CategoryForm, and deliberately so: this is the third model
    in the project whose uniqueness is per-user, and the third time `user` is
    kept out of the form so ownership cannot be reassigned by a crafted POST.
    """

    class Meta:
        model = Participant
        fields = ["name"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_name(self):
        name = self.cleaned_data["name"].strip()

        # As with categories: the DB holds UniqueConstraint(user, name), but a
        # ModelForm cannot check a constraint touching a field the form
        # excludes. Without this a duplicate is an IntegrityError 500.
        duplicates = Participant.objects.filter(user=self.user, name__iexact=name)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError("You already have someone with this name.")

        return name


class ExpenseForm(forms.ModelForm):
    """Form for a user's own expenses."""

    class Meta:
        model = Expense
        fields = ["category", "amount", "spent_on", "note", "participants"]
        widgets = {
            "spent_on": forms.DateInput(attrs={"type": "date"}),
            "note": forms.TextInput(attrs={"placeholder": "Optional"}),
            # A multi-select box hides how many are chosen and needs a modifier
            # key to pick more than one. Checkboxes show the whole set and its
            # state at a glance, which is what this field is actually for.
            "participants": forms.CheckboxSelectMultiple,
        }
        labels = {"participants": "Split evenly with"}
        help_texts = {
            "participants": "Leave empty if this expense is only yours.",
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        # The subtle one. A ModelChoiceField defaults to *every* Category in
        # the table, so without this the dropdown leaks other users' category
        # names, and a crafted POST could file an expense against one of them.
        # Scoping the queryset fixes both the display and the validation,
        # because ModelChoiceField re-queries it when cleaning the field.
        self.fields["category"].queryset = Category.objects.filter(user=user)
        self.fields["category"].empty_label = "Select a category"

        # Exactly the same trap, one field along. ModelMultipleChoiceField
        # also defaults to every row in the table, so an unscoped queryset
        # lists every other user's people and lets a crafted POST attach
        # them. Third time this bug has been available in this project;
        # scoping the queryset is the only thing that closes it, because
        # the field re-queries it when cleaning.
        self.fields["participants"].queryset = Participant.objects.filter(user=user)

    def clean_amount(self):
        amount = self.cleaned_data["amount"]

        # Mirrors CheckConstraint(amount > 0) on the model. Same two-layer
        # split as clean_name above: the DB refuses bad data, the form
        # explains it in language a person can act on.
        if amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")

        return amount


class BaseExpenseItemFormSet(BaseInlineFormSet):
    """Line items, and the invariant the database cannot hold.

    ``CheckConstraint`` works within one row. "These children must sum to
    their parent's amount" spans rows, so no constraint can express it and it
    has to live here, backed by a transaction so a half-written split is
    never committed.

    That is the honest version of a rule people often try to push into the
    schema. The database still guarantees what it can -- every item costs
    something, every share has a positive weight -- and the form guarantees
    what the database cannot see.
    """

    def clean(self):
        super().clean()

        # If individual forms already failed, the totals are meaningless and
        # a second error about them would only add noise.
        if any(self.errors):
            return

        items = [
            form.cleaned_data
            for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
        ]

        # Itemising is optional. An expense with no items is either yours
        # alone or an even split, both of which are valid.
        if not items:
            return

        total = sum((item["amount"] for item in items), Decimal("0"))
        expected = self.instance.amount

        # None when the parent form failed its own validation.
        if expected is None:
            return

        if total != expected:
            difference = abs(total - expected)
            raise forms.ValidationError(
                f"The items add up to {total}, but the expense is {expected}. "
                f"That is {difference} out. Add a line for the difference, or "
                f"correct the amounts.",
                code="items_do_not_sum",
            )


ExpenseItemFormSet = inlineformset_factory(
    Expense,
    ExpenseItem,
    formset=BaseExpenseItemFormSet,
    fields=["name", "amount"],
    widgets={
        "name": forms.TextInput(attrs={"placeholder": "What was it?"}),
        "amount": forms.NumberInput(attrs={"step": "0.01", "placeholder": "0.00"}),
    },
    extra=3,
    can_delete=True,
)
