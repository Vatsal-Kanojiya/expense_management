"""Regression tests for the session 21 review of the handoff implementation.

Each test pins one bug the review found, so it cannot quietly return.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from expenses.balances import balances
from expenses.models import Category, Expense, ExpenseItem, Participant, Settlement
from expenses.settlements import settle_up

User = get_user_model()


class ReviewFixTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!", first_name="Alice"
        )
        cls.bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")
        cls.food = Category.objects.create(user=cls.alice, name="Food")
        cls.rahul = Participant.objects.create(user=cls.alice, name="Rahul")
        cls.bobs_friend = Participant.objects.create(user=cls.bob, name="Neha")

    def test_the_self_name_avoids_an_existing_contact(self):
        Participant.objects.create(user=self.alice, name="alice (SELF)")

        me = Participant.get_or_create_self(self.alice)

        self.assertEqual(me.name, "Alice (self) 2")

    def test_the_api_refuses_another_users_participant_as_payer(self):
        self.client.force_login(self.alice)

        response = self.client.post(
            reverse("api:v1:expense-list"),
            {
                "category": self.food.pk,
                "amount": "300.00",
                "spent_on": "2026-02-01",
                "note": "Dinner",
                "paid_by": self.bobs_friend.pk,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("paid_by", response.json())

    def test_the_api_counts_the_owner_by_default(self):
        self.client.force_login(self.alice)

        self.client.post(
            reverse("api:v1:expense-list"),
            {
                "category": self.food.pk,
                "amount": "300.00",
                "spent_on": "2026-02-01",
                "note": "Dinner",
                "participants": [self.rahul.pk],
            },
            content_type="application/json",
        )

        self.assertEqual(balances(self.alice), [(self.rahul, Decimal("150.00"))])

    def test_reading_balances_creates_nothing(self):
        balances(self.alice)

        self.assertFalse(Participant.objects.filter(user=self.alice, is_self=True).exists())

    def test_settling_a_debt_you_owe_records_a_negative_amount(self):
        me = Participant.get_or_create_self(self.alice)
        dinner = Expense.objects.create(
            user=self.alice,
            category=self.food,
            amount=Decimal("300.00"),
            spent_on="2026-02-01",
            paid_by=self.rahul,
        )
        dinner.participants.add(me, self.rahul)

        settlement = settle_up(self.alice, self.rahul.pk)

        self.assertEqual(settlement.amount, Decimal("-150.00"))
        self.assertIsNone(settle_up(self.alice, self.rahul.pk))

    def test_the_audit_and_the_predicate_agree_at_exactly_one_rupee(self):
        # The reviewer's case: SQLite computed the gap as 0.9999...
        expense = Expense.objects.create(
            user=self.alice,
            category=self.food,
            amount=Decimal("32.91"),
            spent_on="2026-02-01",
            misc_amount=Decimal("17.00"),
            misc_note="Tip",
        )
        ExpenseItem.objects.create(expense=expense, name="Tea", amount=Decimal("14.91"))

        self.assertFalse(Expense.objects.get(pk=expense.pk).is_balanced())
        self.assertIn(expense, Expense.objects.unbalanced())

    def test_an_unticked_line_is_refused_when_the_owner_is_out(self):
        self.client.force_login(self.alice)

        response = self.client.post(
            reverse("expenses:expense_create"),
            {
                "category": self.food.pk,
                "amount": "120.00",
                "spent_on": "2026-02-01",
                "note": "Group order",
                "participants": [self.rahul.pk],
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-name": "Garlic bread",
                "items-0-amount": "120.00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "choose who had this item")
        self.assertFalse(Expense.objects.exists())

    def test_the_balances_page_shows_what_you_owe(self):
        me = Participant.get_or_create_self(self.alice)
        dinner = Expense.objects.create(
            user=self.alice,
            category=self.food,
            amount=Decimal("300.00"),
            # The page defaults to the current month.
            spent_on=date.today(),
            paid_by=self.rahul,
        )
        dinner.participants.add(me, self.rahul)
        self.client.force_login(self.alice)

        response = self.client.get(reverse("expenses:balances"))

        self.assertContains(response, "You owe")
        self.assertEqual(response.context["you_owe"], [(self.rahul, Decimal("150.00"))])
        self.assertEqual(Settlement.objects.count(), 0)
