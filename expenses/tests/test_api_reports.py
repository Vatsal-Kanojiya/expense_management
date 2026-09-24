"""Dashboard summary, balances and settling up through the API (phase 20.5)."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from expenses.models import Category, Expense, Participant, Settlement

User = get_user_model()


def url(name, *args):
    return reverse(f"api:v1:{name}", args=args)


class ReportTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", "pw-Alice-123")
        cls.bob = User.objects.create_user("bob", "bob@example.com", "pw-Bob-12345")
        cls.me = Participant.get_or_create_self(cls.alice)
        cls.food = Category.objects.create(user=cls.alice, name="Food")
        cls.travel = Category.objects.create(user=cls.alice, name="Travel")
        cls.rahul = Participant.objects.create(user=cls.alice, name="Rahul")
        cls.priya = Participant.objects.create(user=cls.alice, name="Priya")

    def setUp(self):
        self.client.force_login(self.alice)

    def expense(self, amount, day, category=None, paid_by=None, split_with=()):
        expense = Expense.objects.create(
            user=self.alice,
            category=category or self.food,
            amount=Decimal(amount),
            spent_on=day,
            paid_by=paid_by,
        )
        if split_with:
            expense.participants.set([self.me, *split_with])
        return expense


class SummaryTests(ReportTestCase):
    def test_a_whole_month_against_the_month_before(self):
        self.expense("300", date(2026, 3, 3))
        self.expense("100", date(2026, 3, 20), category=self.travel)
        self.expense("200", date(2026, 2, 14))

        body = self.client.get(url("summary") + "?start=2026-03-01&end=2026-03-31").json()

        self.assertEqual((body["total"], body["count"], body["average"]), ("400.00", 2, "200.00"))
        self.assertEqual(body["biggest"]["amount"], "300.00")
        self.assertEqual(
            [(row["category_name"], row["total"], row["share"]) for row in body["by_category"]],
            [("Food", "300.00", "75.00"), ("Travel", "100.00", "25.00")],
        )
        self.assertEqual(
            (body["previous"]["start"], body["previous"]["total"]), ("2026-02-01", "200.00")
        )
        self.assertEqual(body["change_percent"], "100.00")

    def test_nothing_before_means_no_percentage(self):
        self.expense("50", date(2026, 3, 3))

        body = self.client.get(url("summary") + "?start=2026-03-01&end=2026-03-31").json()

        self.assertIsNone(body["change_percent"])

    def test_the_default_is_the_current_month(self):
        body = self.client.get(url("summary")).json()

        self.assertEqual(body["start"][8:], "01")
        self.assertIsNone(body["biggest"])

    def test_bad_dates_are_a_400(self):
        response = self.client.get(url("summary") + "?start=2026-03-31&end=2026-03-01")

        self.assertEqual(response.status_code, 400)
        self.assertIn("non_field_errors", response.json())


class BalanceTests(ReportTestCase):
    def test_both_directions_and_the_totals(self):
        self.expense("300", date(2026, 3, 3), split_with=[self.rahul])  # Rahul owes 150
        self.expense(
            "200", date(2026, 3, 4), paid_by=self.priya, split_with=[self.priya]
        )  # you owe 100

        body = self.client.get(url("balances")).json()

        self.assertEqual(
            body["owes_you"],
            [{"participant": {"id": self.rahul.id, "name": "Rahul"}, "amount": "150.00"}],
        )
        self.assertEqual(
            body["you_owe"],
            [{"participant": {"id": self.priya.id, "name": "Priya"}, "amount": "100.00"}],
        )
        self.assertEqual((body["owes_you_total"], body["you_owe_total"]), ("150.00", "100.00"))
        self.assertEqual((body["start"], body["end"]), (None, None))

    def test_settling_up_clears_the_balance_once(self):
        self.expense("300", date(2026, 3, 3), split_with=[self.rahul])

        first = self.client.post(
            url("settle-up", self.rahul.id), {"note": "cash"}, content_type="application/json"
        )
        again = self.client.post(
            url("settle-up", self.rahul.id), {}, content_type="application/json"
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(
            (first.json()["settlement"]["amount"], first.json()["settlement"]["note"]),
            ("150.00", "cash"),
        )
        self.assertEqual((again.status_code, again.json()["code"]), (200, "nothing_outstanding"))
        self.assertEqual(self.client.get(url("balances")).json()["owes_you"], [])
        # Gross stays: "Rahul owed 150 and has repaid 150" is two numbers.
        self.assertEqual(self.client.get(url("balances")).json()["gross"][0]["amount"], "150.00")

    def test_settling_what_you_owe_is_recorded_as_negative(self):
        self.expense("200", date(2026, 3, 4), paid_by=self.priya, split_with=[self.priya])

        body = self.client.post(
            url("settle-up", self.priya.id), {}, content_type="application/json"
        ).json()

        self.assertEqual(body["settlement"]["amount"], "-100.00")

    def test_someone_elses_person_is_a_404(self):
        theirs = Participant.objects.create(user=self.bob, name="Stranger")

        response = self.client.post(
            url("settle-up", theirs.id), {}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Settlement.objects.exists())

    def test_the_history_is_scoped_and_filterable(self):
        self.expense("300", date(2026, 3, 3), split_with=[self.rahul, self.priya])
        self.client.post(url("settle-up", self.rahul.id), {}, content_type="application/json")
        self.client.post(url("settle-up", self.priya.id), {}, content_type="application/json")
        stranger = Participant.objects.create(user=self.bob, name="Stranger")
        Settlement.objects.create(user=self.bob, participant=stranger, amount=Decimal("5"))

        everything = self.client.get(url("settlement-list")).json()["results"]
        rahuls = self.client.get(url("settlement-list") + f"?participant={self.rahul.id}").json()[
            "results"
        ]

        self.assertEqual(len(everything), 2)
        self.assertEqual([row["participant_name"] for row in rahuls], ["Rahul"])
