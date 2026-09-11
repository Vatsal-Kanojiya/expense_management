"""The security boundary, in one readable file.

Every test here asks the same question: can Alice reach, change or
destroy something belonging to Bob? The answer must always be no, and
the failure mode must be 404 rather than 403 — a 403 confirms the row
exists, which leaks the very thing scoping is meant to hide.

This is the file to read first when reviewing, and the one that must
never be allowed to go red.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from expenses.models import Category, Expense
from expenses.tests.helpers import item_formset

User = get_user_model()


class OwnershipBoundaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")

        cls.alice_food = Category.objects.create(user=cls.alice, name="Food")
        cls.bob_rent = Category.objects.create(user=cls.bob, name="Rent")

        cls.alice_lunch = Expense.objects.create(
            user=cls.alice,
            category=cls.alice_food,
            amount=Decimal("10.00"),
            spent_on=date(2026, 9, 1),
            note="Alice lunch",
        )
        cls.bob_rent_payment = Expense.objects.create(
            user=cls.bob,
            category=cls.bob_rent,
            amount=Decimal("900.00"),
            spent_on=date(2026, 9, 1),
            note="Bob rent",
        )

    def setUp(self):
        self.client.force_login(self.alice)

    # ---- Listing: you see only your own -------------------------------

    def test_expense_list_excludes_other_users(self):
        response = self.client.get(reverse("expenses:expense_list"))

        self.assertContains(response, "Alice lunch")
        self.assertNotContains(response, "Bob rent")
        self.assertEqual(list(response.context["expenses"]), [self.alice_lunch])

    def test_category_list_excludes_other_users(self):
        response = self.client.get(reverse("expenses:category_list"))

        self.assertContains(response, "Food")
        self.assertNotContains(response, "Rent")

    # ---- Reading someone else's row: 404, not 403 ---------------------

    def test_cannot_open_another_users_expense_edit_form(self):
        response = self.client.get(
            reverse("expenses:expense_update", args=[self.bob_rent_payment.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_cannot_open_another_users_category_edit_form(self):
        response = self.client.get(reverse("expenses:category_update", args=[self.bob_rent.pk]))

        self.assertEqual(response.status_code, 404)

    def test_cannot_open_another_users_delete_confirmation(self):
        for name, pk in [
            ("expenses:expense_delete", self.bob_rent_payment.pk),
            ("expenses:category_delete", self.bob_rent.pk),
        ]:
            with self.subTest(view=name):
                self.assertEqual(self.client.get(reverse(name, args=[pk])).status_code, 404)

    # ---- Writing to someone else's row: refused AND unchanged ---------

    def test_cannot_update_another_users_expense(self):
        response = self.client.post(
            reverse("expenses:expense_update", args=[self.bob_rent_payment.pk]),
            {
                "category": self.alice_food.pk,
                "amount": "1.00",
                "spent_on": "2026-09-02",
                "note": "hijacked",
                **item_formset(),
            },
        )

        self.assertEqual(response.status_code, 404)

        # Status codes are not enough: assert the row is untouched.
        self.bob_rent_payment.refresh_from_db()
        self.assertEqual(self.bob_rent_payment.amount, Decimal("900.00"))
        self.assertEqual(self.bob_rent_payment.note, "Bob rent")
        self.assertEqual(self.bob_rent_payment.user, self.bob)

    def test_cannot_update_another_users_category(self):
        response = self.client.post(
            reverse("expenses:category_update", args=[self.bob_rent.pk]),
            {"name": "hijacked"},
        )

        self.assertEqual(response.status_code, 404)
        self.bob_rent.refresh_from_db()
        self.assertEqual(self.bob_rent.name, "Rent")

    def test_cannot_delete_another_users_expense(self):
        response = self.client.post(
            reverse("expenses:expense_delete", args=[self.bob_rent_payment.pk])
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Expense.objects.filter(pk=self.bob_rent_payment.pk).exists())

    def test_cannot_delete_another_users_category(self):
        response = self.client.post(reverse("expenses:category_delete", args=[self.bob_rent.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Category.objects.filter(pk=self.bob_rent.pk).exists())

    # ---- Ownership cannot be forged through a form --------------------

    def test_cannot_file_an_expense_against_another_users_category(self):
        response = self.client.post(
            reverse("expenses:expense_create"),
            {
                "category": self.bob_rent.pk,
                "amount": "5.00",
                "spent_on": "2026-09-02",
                "note": "sneaky",
                **item_formset(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("category", response.context["form"].errors)
        self.assertFalse(Expense.objects.filter(note="sneaky").exists())

    def test_posting_a_user_field_does_not_reassign_ownership(self):
        # `user` is not a form field, so an extra POST key must be ignored
        # rather than honoured.
        self.client.post(
            reverse("expenses:category_create"),
            {"name": "Travel", "user": self.bob.pk},
        )

        self.assertEqual(Category.objects.get(name="Travel").user, self.alice)

    def test_moving_an_expense_to_another_users_category_is_rejected(self):
        response = self.client.post(
            reverse("expenses:expense_update", args=[self.alice_lunch.pk]),
            {
                "category": self.bob_rent.pk,
                "amount": "10.00",
                "spent_on": "2026-09-01",
                "note": "Alice lunch",
                **item_formset(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("category", response.context["form"].errors)
        self.alice_lunch.refresh_from_db()
        self.assertEqual(self.alice_lunch.category, self.alice_food)

    # ---- A nonexistent row behaves the same as someone else's ---------

    def test_missing_row_is_indistinguishable_from_a_forbidden_one(self):
        """Both must be 404, so response codes cannot be used to probe
        which ids exist in the table."""
        missing = 999_999

        forbidden = self.client.get(
            reverse("expenses:expense_update", args=[self.bob_rent_payment.pk])
        )
        absent = self.client.get(reverse("expenses:expense_update", args=[missing]))

        self.assertEqual(forbidden.status_code, absent.status_code)
