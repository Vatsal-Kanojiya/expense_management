from django import forms

from .models import Category, Expense, Participant


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
        fields = ["category", "amount", "spent_on", "note"]
        widgets = {
            "spent_on": forms.DateInput(attrs={"type": "date"}),
            "note": forms.TextInput(attrs={"placeholder": "Optional"}),
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

    def clean_amount(self):
        amount = self.cleaned_data["amount"]

        # Mirrors CheckConstraint(amount > 0) on the model. Same two-layer
        # split as clean_name above: the DB refuses bad data, the form
        # explains it in language a person can act on.
        if amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")

        return amount
