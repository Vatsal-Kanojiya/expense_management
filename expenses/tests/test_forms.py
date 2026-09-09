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

from expenses.forms import CategoryForm, ExpenseForm
from expenses.models import Category

User = get_user_model()


class CategoryFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw12345!")
        cls.bob = User.objects.create_user("bob", password="pw12345!")
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


class ExpenseFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw12345!")
        cls.bob = User.objects.create_user("bob", password="pw12345!")
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

    def test_note_is_optional(self):
        form = ExpenseForm(data=self._data(note=""), user=self.alice)

        self.assertTrue(form.is_valid(), form.errors)

    def test_amount_keeps_two_decimal_places(self):
        form = ExpenseForm(data=self._data(amount="25.99"), user=self.alice)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["amount"], Decimal("25.99"))
