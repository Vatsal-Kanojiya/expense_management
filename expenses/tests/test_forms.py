"""Form-level tests: what the *application* explains.

The DB constraints in test_models.py guarantee correctness. These cover
the layer that turns a would-be IntegrityError into a field error a
person can act on, plus the queryset scoping that stops a form offering
another user's data.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from expenses.forms import CategoryForm, ExpenseForm, ExpenseItemForm, ParticipantForm
from expenses.models import Category, Expense, Participant
from expenses.widgets import ChipSelectMultiple

User = get_user_model()


class CategoryFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")
        cls.alice_food = Category.objects.create(user=cls.alice, name="Food")

    def test_user_is_not_a_form_field(self):
        # If it were, a crafted POST could reassign ownership. The view
        # supplies the user out of band instead.
        self.assertNotIn("user", CategoryForm(user=self.alice).fields)

    def test_new_name_is_valid(self):
        form = CategoryForm(data={"name": "Travel"}, user=self.alice)

        self.assertTrue(form.is_valid(), form.errors)

    def test_duplicate_name_is_a_field_error_not_a_500(self):
        form = CategoryForm(data={"name": "Food"}, user=self.alice)

        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)

    def test_duplicate_check_ignores_case(self):
        form = CategoryForm(data={"name": "FOOD"}, user=self.alice)

        self.assertFalse(form.is_valid())

    def test_name_is_stripped(self):
        form = CategoryForm(data={"name": "  Travel  "}, user=self.alice)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["name"], "Travel")

    def test_another_users_name_is_not_a_duplicate(self):
        # Uniqueness is per user, so Bob may also have "Food".
        form = CategoryForm(data={"name": "Food"}, user=self.bob)

        self.assertTrue(form.is_valid(), form.errors)

    def test_editing_a_category_does_not_collide_with_itself(self):
        # The duplicate query must exclude the instance being edited,
        # otherwise renaming "Food" to "Food" reports a false duplicate.
        form = CategoryForm(data={"name": "Food"}, user=self.alice, instance=self.alice_food)

        self.assertTrue(form.is_valid(), form.errors)

    def test_create_form_focuses_the_first_field(self):
        form = CategoryForm(user=self.alice)
        self.assertTrue(form.fields["name"].widget.attrs.get("autofocus"))

    def test_edit_form_does_not_autofocus(self):
        form = CategoryForm(data={"name": "Food"}, user=self.alice, instance=self.alice_food)
        self.assertNotIn("autofocus", form.fields["name"].widget.attrs)


class ParticipantFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.rahul = Participant.objects.create(user=cls.alice, name="Rahul")

    def test_create_form_focuses_the_first_field(self):
        form = ParticipantForm(user=self.alice)
        self.assertTrue(form.fields["name"].widget.attrs.get("autofocus"))

    def test_edit_form_does_not_autofocus(self):
        form = ParticipantForm(user=self.alice, instance=self.rahul)
        self.assertNotIn("autofocus", form.fields["name"].widget.attrs)

    def test_name_you_is_reserved_for_self(self):
        form = ParticipantForm(data={"name": "You"}, user=self.alice)
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)

        form_lower = ParticipantForm(data={"name": "you"}, user=self.alice)
        self.assertFalse(form_lower.is_valid())


class ExpenseFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")
        cls.alice_food = Category.objects.create(user=cls.alice, name="Food")
        cls.bob_rent = Category.objects.create(user=cls.bob, name="Rent")

    def _data(self, **overrides):
        defaults = {
            "category": self.alice_food.pk,
            "amount": "25.00",
            "spent_on": date(2026, 9, 5),
            "note": "Lunch",
        }
        return {**defaults, **overrides}

    def test_user_is_not_a_form_field(self):
        self.assertNotIn("user", ExpenseForm(user=self.alice).fields)

    def test_category_choices_are_limited_to_the_user(self):
        # The subtle one. A ModelChoiceField defaults to every row in the
        # table, so without scoping the dropdown leaks other users' category
        # names.
        choices = ExpenseForm(user=self.alice).fields["category"].queryset

        self.assertEqual(list(choices), [self.alice_food])

    def test_posting_another_users_category_is_rejected(self):
        # Same scoping, doing its second job: ModelChoiceField re-queries the
        # queryset when cleaning, so a crafted pk cannot get through.
        form = ExpenseForm(data=self._data(category=self.bob_rent.pk), user=self.alice)

        self.assertFalse(form.is_valid())
        self.assertIn("category", form.errors)

    def test_valid_expense(self):
        form = ExpenseForm(data=self._data(), user=self.alice)

        self.assertTrue(form.is_valid(), form.errors)

    def test_zero_amount_is_rejected(self):
        form = ExpenseForm(data=self._data(amount="0"), user=self.alice)

        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)

    def test_negative_amount_is_rejected(self):
        form = ExpenseForm(data=self._data(amount="-5"), user=self.alice)

        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)

    def test_note_is_required(self):
        """Required on the form, blank=True on the model, and both are right.

        Rows written before this rule have empty notes and no migration can
        invent text for them, so the column stays permissive and the demand
        is made where it applies -- to new input.
        """
        form = ExpenseForm(data=self._data(note=""), user=self.alice)

        self.assertFalse(form.is_valid())
        self.assertIn("note", form.errors)

    def test_amount_keeps_two_decimal_places(self):
        form = ExpenseForm(data=self._data(amount="25.99"), user=self.alice)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["amount"], Decimal("25.99"))

    def test_create_form_focuses_the_first_field(self):
        form = ExpenseForm(user=self.alice)
        self.assertTrue(form.fields["category"].widget.attrs.get("autofocus"))

    def test_edit_form_does_not_autofocus(self):
        expense = Expense.objects.create(
            user=self.alice,
            category=self.alice_food,
            amount=Decimal("25.00"),
            spent_on=date(2026, 9, 5),
            note="Lunch",
        )
        form = ExpenseForm(user=self.alice, instance=expense)
        self.assertNotIn("autofocus", form.fields["category"].widget.attrs)

    def test_a_bound_date_renders_in_iso_format(self):
        expense = Expense.objects.create(
            user=self.alice,
            category=self.alice_food,
            amount=Decimal("25.00"),
            spent_on=date(2026, 1, 15),
            note="Lunch",
        )
        form = ExpenseForm(user=self.alice, instance=expense)
        self.assertIn('value="2026-01-15"', form.as_p())

    def test_paid_by_defaults_to_self(self):
        self_p = Participant.get_or_create_self(self.alice)
        form = ExpenseForm(user=self.alice)
        self.assertEqual(form.fields["paid_by"].initial, self_p)

    def test_split_includes_self_by_default(self):
        self_p = Participant.get_or_create_self(self.alice)
        form = ExpenseForm(user=self.alice)
        self.assertEqual(form.fields["participants"].initial, [self_p])

    def test_empty_paid_by_defaults_to_self(self):
        self_p = Participant.get_or_create_self(self.alice)
        form = ExpenseForm(data=self._data(), user=self.alice)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["paid_by"], self_p)

    def test_misc_amount_needs_a_note(self):
        form = ExpenseForm(
            data=self._data(misc_amount="50.00", misc_note=""),
            user=self.alice,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("misc_note", form.errors)

    def test_misc_amount_must_be_positive(self):
        form_zero = ExpenseForm(
            data=self._data(misc_amount="0.00", misc_note="Zero"),
            user=self.alice,
        )
        self.assertFalse(form_zero.is_valid())
        self.assertIn("misc_amount", form_zero.errors)

        form_neg = ExpenseForm(
            data=self._data(misc_amount="-5.00", misc_note="Negative"),
            user=self.alice,
        )
        self.assertFalse(form_neg.is_valid())
        self.assertIn("misc_amount", form_neg.errors)

    def test_misc_note_without_amount_is_allowed(self):
        form = ExpenseForm(
            data=self._data(misc_amount="", misc_note="Just a note"),
            user=self.alice,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_participants_use_the_chip_widget(self):
        expense_form = ExpenseForm(user=self.alice)
        self.assertIsInstance(expense_form.fields["participants"].widget, ChipSelectMultiple)

        item_form = ExpenseItemForm(user=self.alice)
        self.assertIsInstance(item_form.fields["shared_with"].widget, ChipSelectMultiple)

    def test_the_widget_falls_back_to_a_plain_multiselect(self):
        form = ExpenseForm(user=self.alice)
        html = form.as_p()
        self.assertIn("<select", html)
        self.assertIn("multiple", html)

    def test_the_widget_queryset_is_still_scoped_to_the_user(self):
        bob = User.objects.create_user("bob_scope", "bob_scope@example.com", "pw12345!")
        bob_p = Participant.objects.create(user=bob, name="Bob Person")
        alice_p = Participant.objects.create(user=self.alice, name="Alice Person")

        expense_form = ExpenseForm(user=self.alice)
        self.assertIn(alice_p, expense_form.fields["participants"].queryset)
        self.assertNotIn(bob_p, expense_form.fields["participants"].queryset)

        item_form = ExpenseItemForm(user=self.alice)
        self.assertIn(alice_p, item_form.fields["shared_with"].queryset)
        self.assertNotIn(bob_p, item_form.fields["shared_with"].queryset)
