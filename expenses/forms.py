from decimal import Decimal

from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils import timezone

from .models import (
    ROUNDING_TOLERANCE,
    Category,
    Expense,
    ExpenseItem,
    ItemShare,
    Participant,
    unaccounted,
)


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
        if not self.instance.pk:
            self.fields["name"].widget.attrs["autofocus"] = True

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
        if not self.instance.pk:
            self.fields["name"].widget.attrs["autofocus"] = True

    def clean_name(self):
        name = self.cleaned_data["name"].strip()

        if name.lower() == "you":
            raise forms.ValidationError("'You' is reserved for your own share.")

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
        fields = [
            "category",
            "amount",
            "spent_on",
            "note",
            "paid_by",
            "participants",
            "misc_amount",
            "misc_note",
        ]
        widgets = {
            "spent_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "note": forms.TextInput(attrs={"placeholder": "What was this for?"}),
            "misc_amount": forms.NumberInput(attrs={"step": "0.01", "placeholder": "0.00"}),
            "misc_note": forms.TextInput(attrs={"placeholder": "e.g. GST, tip, service charge"}),
            # A multi-select box hides how many are chosen and needs a modifier
            # key to pick more than one. Checkboxes show the whole set and its
            # state at a glance, which is what this field is actually for.
            "participants": forms.CheckboxSelectMultiple,
        }
        labels = {
            "paid_by": "Paid by",
            "participants": "Split evenly with",
            "misc_amount": "Tax, tip or other",
            "misc_note": "What was it?",
        }
        help_texts = {
            "paid_by": "Who paid this bill.",
            "participants": "Leave empty if this expense is only yours.",
            "misc_amount": "Leftover, tax, or tip included in the total bill.",
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        # Category, amount and note are what an expense has to carry to be
        # worth keeping; everything else can be filled in later. The model
        # leaves `note` blank=True because rows predating this rule exist and
        # a migration cannot invent text for them, so the requirement is
        # stated here, where it applies to new input only.
        self.fields["note"].required = True

        # A date is required by the column, and asking for one adds nothing
        # when almost every expense is entered the day it happened. Today is
        # the answer nine times in ten and is still editable.
        if not self.instance.pk:
            self.fields["spent_on"].initial = timezone.localdate
            self.fields["category"].widget.attrs["autofocus"] = True

        # The subtle one. A ModelChoiceField defaults to *every* Category in
        # the table, so without this the dropdown leaks other users' category
        # names, and a crafted POST could file an expense against one of them.
        # Scoping the queryset fixes both the display and the validation,
        # because ModelChoiceField re-queries it when cleaning the field.
        self.fields["category"].queryset = Category.objects.filter(user=user)
        self.fields["category"].empty_label = "Select a category"

        # Payer defaults to the user themselves, but can be any participant.
        self_participant = Participant.get_or_create_self(user) if user else None
        self.fields["paid_by"].queryset = Participant.objects.filter(user=user)
        self.fields["paid_by"].empty_label = None
        self.fields["paid_by"].required = False
        if not self.instance.pk and self_participant:
            self.fields["paid_by"].initial = self_participant

        # Exactly the same trap, one field along. ModelMultipleChoiceField
        # also defaults to every row in the table, so an unscoped queryset
        # lists every other user's people and lets a crafted POST attach
        # them. Third time this bug has been available in this project;
        # scoping the queryset is the only thing that closes it, because
        # the field re-queries it when cleaning.
        self.fields["participants"].queryset = Participant.objects.filter(user=user)
        if not self.instance.pk and self_participant:
            self.fields["participants"].initial = [self_participant]

    def clean_paid_by(self):
        paid_by = self.cleaned_data.get("paid_by")
        if not paid_by and self.user:
            return Participant.get_or_create_self(self.user)
        return paid_by

    def clean_amount(self):
        amount = self.cleaned_data["amount"]

        # Mirrors CheckConstraint(amount > 0) on the model. Same two-layer
        # split as clean_name above: the DB refuses bad data, the form
        # explains it in language a person can act on.
        if amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")

        return amount

    def clean_misc_amount(self):
        amount = self.cleaned_data.get("misc_amount")
        if amount is not None and amount <= 0:
            raise forms.ValidationError("Misc amount must be greater than zero.")
        return amount

    def clean(self):
        cleaned_data = super().clean()
        misc_amount = cleaned_data.get("misc_amount")
        misc_note = (cleaned_data.get("misc_note") or "").strip()
        if misc_amount and not misc_note:
            self.add_error("misc_note", "Please describe what this misc amount is for.")
        return cleaned_data


class ExpenseItemForm(forms.ModelForm):
    """One line, plus who shared it.

    ``shared_with`` is not a model field. It stands in for ItemShare rows,
    which is the ordinary way to edit a through model from a form: expose
    the relationship as a multiple-choice field and reconcile the rows on
    save. Editing the through model directly would mean a formset inside a
    formset, which is a lot of machinery for a checkbox list.

    Every share written here has weight 1, an equal split of that line. The
    weight column exists for unequal shares, which no UI exposes yet.

    "In addition to you" is the convention throughout: the owner always
    counts as one share of anything that is shared at all.
    """

    shared_with = forms.ModelMultipleChoiceField(
        queryset=Participant.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Shared with (besides you)",
    )

    class Meta:
        model = ExpenseItem
        fields = ["name", "amount"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "What was it?"}),
            "amount": forms.NumberInput(attrs={"step": "0.01", "placeholder": "0.00"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        # The same scoping rule as every other choice field in this project.
        self.fields["shared_with"].queryset = Participant.objects.filter(user=user)

        if self.instance.pk:
            self.fields["shared_with"].initial = list(
                self.instance.shares.values_list("participant_id", flat=True)
            )


class BaseExpenseItemFormSet(BaseInlineFormSet):
    """Line items, and the invariant the database cannot hold.

    ``CheckConstraint`` works within one row. "These children must sum to
    their parent's amount" spans rows, so no constraint can express it and it
    has to live here, backed by a transaction so a half-written split is
    never committed.

    That is the honest version of a rule people often try to push into the
    schema. The database still guarantees what it can -- every item costs
    something, every share has a positive weight.

    What changed is the consequence. The rule is still checked here, but a
    breach no longer refuses the submission: it is recorded on
    ``sum_mismatch`` and the expense saves anyway. Blocking cost a whole
    form's worth of typing over a single wrong figure. The guarantee that
    replaces it lives in ``balances``, which skips an expense that does not
    add up rather than counting a partial split as a complete one.
    """

    #: Set by ``clean`` to ``(items_total, expense_amount)`` when the two
    #: disagree, and left None otherwise. Not an error -- a fact the view
    #: reports back to the person after saving.
    sum_mismatch = None

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

        if getattr(self.instance, "misc_amount", None) and not items:
            raise forms.ValidationError(
                "A misc amount can only be added to an itemised expense with line items."
            )

        # Itemising is optional. An expense with no items is either yours
        # alone or an even split, both of which are valid.
        if not items:
            return

        total = sum((item["amount"] for item in items), Decimal("0"))
        expected = self.instance.amount

        # None when the parent form failed its own validation.
        if expected is None:
            return

        diff = unaccounted(expected, total, getattr(self.instance, "misc_amount", None))
        if abs(diff) >= ROUNDING_TOLERANCE:
            # Recorded, not raised. Refusing the whole submission over this
            # threw away everything else the person had typed, and a refresh
            # lost it for good -- a steep price for one wrong figure. The
            # expense saves; `Expense.is_balanced` reports the mismatch and
            # `balances` skips the expense until it is fixed, so nothing
            # half-entered is ever counted as a whole split. The view reads
            # this attribute to warn.
            self.sum_mismatch = (diff, expected)

    def save(self, commit=True):
        items = super().save(commit=commit)

        if commit:
            for form in self.forms:
                if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                    continue
                if form.instance.pk:
                    self._sync_shares(form.instance, form.cleaned_data.get("shared_with", []))

        return items

    @staticmethod
    def _sync_shares(item, participants):
        """Reconcile ItemShare rows to match the checkboxes.

        Deliberately a diff, not delete-then-recreate. Recreating would churn
        primary keys on every save and throw away the weight column, which
        nothing in the UI sets yet but the schema supports.
        """
        wanted = {participant.pk for participant in participants}
        existing = set(item.shares.values_list("participant_id", flat=True))

        item.shares.filter(participant_id__in=existing - wanted).delete()
        ItemShare.objects.bulk_create(
            [ItemShare(item=item, participant_id=pk) for pk in wanted - existing]
        )


ExpenseItemFormSet = inlineformset_factory(
    Expense,
    ExpenseItem,
    form=ExpenseItemForm,
    formset=BaseExpenseItemFormSet,
    fields=["name", "amount"],
    # One blank row, not three. Three was a guess at how many lines a typical
    # expense has, paid for by everyone who itemises fewer -- and there was no
    # way to ask for a fourth. `item-formset.js` adds rows on demand, so the
    # server only has to render the one that gets the person started.
    extra=1,
    can_delete=True,
)
