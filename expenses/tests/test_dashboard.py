"""Dashboard and expense-list filtering.

The aggregation maths is covered in test_summaries.py; these cover the
view layer around it — defaults, query-string handling, scoping and the
query budget.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from expenses.models import Category, Expense

User = get_user_model()


class DashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")
        cls.rent = Category.objects.create(user=cls.alice, name="Rent")
        cls.food = Category.objects.create(user=cls.alice, name="Food")
        cls.bob_cat = Category.objects.create(user=cls.bob, name="BobOnly")

        Expense.objects.create(
            user=cls.alice, category=cls.rent, amount=Decimal("8400"), spent_on=date(2026, 9, 3)
        )
        Expense.objects.create(
            user=cls.alice, category=cls.food, amount=Decimal("600"), spent_on=date(2026, 9, 20)
        )
        Expense.objects.create(
            user=cls.alice, category=cls.food, amount=Decimal("1000"), spent_on=date(2026, 8, 15)
        )
        Expense.objects.create(
            user=cls.bob, category=cls.bob_cat, amount=Decimal("55555"), spent_on=date(2026, 9, 5)
        )

    def setUp(self):
        self.client.force_login(self.alice)

    def test_dashboard_requires_login(self):
        self.client.logout()

        response = self.client.get(reverse("expenses:dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_dashboard_is_at_the_site_root(self):
        self.assertEqual(reverse("expenses:dashboard"), "/")

    @patch("expenses.filters.date")
    def test_defaults_to_the_current_month(self, mock_date):
        # Patching the date the form reads keeps the default deterministic
        # rather than depending on the day the suite happens to run.
        mock_date.today.return_value = date(2026, 9, 9)
        mock_date.side_effect = date

        response = self.client.get(reverse("expenses:dashboard"))

        summary = response.context["summary"]
        self.assertEqual(summary.start, date(2026, 9, 1))
        self.assertEqual(summary.end, date(2026, 9, 30))
        self.assertEqual(summary.total, Decimal("9000"))

    def test_custom_date_range_is_honoured(self):
        response = self.client.get(
            reverse("expenses:dashboard"), {"start": "2026-09-01", "end": "2026-09-10"}
        )

        summary = response.context["summary"]
        self.assertEqual(summary.start, date(2026, 9, 1))
        self.assertEqual(summary.end, date(2026, 9, 10))
        # Only the 8400 on the 3rd falls inside.
        self.assertEqual(summary.total, Decimal("8400"))

    def test_whole_month_compares_against_the_previous_month(self):
        response = self.client.get(
            reverse("expenses:dashboard"), {"start": "2026-09-01", "end": "2026-09-30"}
        )

        self.assertEqual(response.context["previous"].start, date(2026, 8, 1))
        self.assertEqual(response.context["previous"].total, Decimal("1000"))
        # 1000 -> 9000 is +800%
        self.assertEqual(response.context["change"], Decimal("800"))

    def test_change_is_none_when_the_previous_period_was_empty(self):
        response = self.client.get(
            reverse("expenses:dashboard"), {"start": "2026-08-01", "end": "2026-08-31"}
        )

        # July had nothing, so there is no comparison to make.
        self.assertIsNone(response.context["change"])
        self.assertContains(response, "Nothing spent in that period")

    def test_other_users_spending_never_appears(self):
        response = self.client.get(
            reverse("expenses:dashboard"), {"start": "2026-09-01", "end": "2026-09-30"}
        )

        self.assertEqual(response.context["summary"].total, Decimal("9000"))
        self.assertNotContains(response, "BobOnly")
        self.assertNotContains(response, "55555")

    def test_reversed_date_range_is_a_form_error_not_a_crash(self):
        response = self.client.get(
            reverse("expenses:dashboard"), {"start": "2026-09-30", "end": "2026-09-01"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)

    def test_unparseable_date_is_a_form_error_not_a_crash(self):
        response = self.client.get(reverse("expenses:dashboard"), {"start": "banana"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("start", response.context["form"].errors)

    def test_empty_period_renders_without_dividing_by_zero(self):
        response = self.client.get(
            reverse("expenses:dashboard"), {"start": "2020-01-01", "end": "2020-01-31"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"].total, Decimal("0"))

    def test_category_shares_are_computed(self):
        response = self.client.get(
            reverse("expenses:dashboard"), {"start": "2026-09-01", "end": "2026-09-30"}
        )

        rows = {r["category__name"]: r for r in response.context["summary"].by_category}
        self.assertEqual(round(rows["Rent"]["share"]), 93)
        self.assertEqual(round(rows["Food"]["share"]), 7)

    def test_dashboard_query_count_is_flat(self):
        # Session, user, then three queries per period for two periods.
        # Independent of how many expenses or categories exist.
        with self.assertNumQueries(8):
            self.client.get(
                reverse("expenses:dashboard"), {"start": "2026-09-01", "end": "2026-09-30"}
            )

        for _ in range(20):
            Expense.objects.create(
                user=self.alice, category=self.food, amount=1, spent_on=date(2026, 9, 12)
            )

        with self.assertNumQueries(8):
            self.client.get(
                reverse("expenses:dashboard"), {"start": "2026-09-01", "end": "2026-09-30"}
            )


class ExpenseFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")
        cls.rent = Category.objects.create(user=cls.alice, name="Rent")
        cls.food = Category.objects.create(user=cls.alice, name="Food")
        cls.bob_cat = Category.objects.create(user=cls.bob, name="BobOnly")

        cls.sept_rent = Expense.objects.create(
            user=cls.alice,
            category=cls.rent,
            amount=Decimal("8400"),
            spent_on=date(2026, 9, 3),
            note="September rent",
        )
        cls.sept_milk = Expense.objects.create(
            user=cls.alice,
            category=cls.food,
            amount=Decimal("250"),
            spent_on=date(2026, 9, 20),
            note="Milk and bread",
        )
        cls.aug_food = Expense.objects.create(
            user=cls.alice,
            category=cls.food,
            amount=Decimal("1000"),
            spent_on=date(2026, 8, 15),
            note="August groceries",
        )

    def setUp(self):
        self.client.force_login(self.alice)

    def _get(self, **params):
        return self.client.get(reverse("expenses:expense_list"), params)

    def test_date_range_filters(self):
        response = self._get(start="2026-09-01", end="2026-09-30")

        self.assertEqual(set(response.context["expenses"]), {self.sept_rent, self.sept_milk})

    def test_category_filters(self):
        response = self._get(start="2026-01-01", end="2026-12-31", category=self.food.pk)

        self.assertEqual(set(response.context["expenses"]), {self.sept_milk, self.aug_food})

    def test_search_matches_the_note_case_insensitively(self):
        response = self._get(start="2026-01-01", end="2026-12-31", search="MILK")

        self.assertEqual(list(response.context["expenses"]), [self.sept_milk])

    def test_filters_combine(self):
        response = self._get(
            start="2026-09-01", end="2026-09-30", category=self.food.pk, search="milk"
        )

        self.assertEqual(list(response.context["expenses"]), [self.sept_milk])

    def test_total_reflects_the_filtered_set_not_the_page(self):
        response = self._get(start="2026-09-01", end="2026-09-30")

        self.assertEqual(response.context["filtered_total"], Decimal("8650"))

    def test_category_dropdown_excludes_other_users_categories(self):
        response = self._get()

        self.assertEqual(
            list(response.context["form"].fields["category"].queryset), [self.food, self.rent]
        )

    def test_filtering_by_another_users_category_is_rejected(self):
        # Same rule as ExpenseForm: an unscoped queryset here would let a
        # crafted ?category=<id> probe another user's data.
        response = self._get(category=self.bob_cat.pk)

        self.assertIn("category", response.context["form"].errors)

    def test_no_matches_shows_the_filtered_empty_state(self):
        response = self._get(start="2026-01-01", end="2026-12-31", search="nothing-matches")

        self.assertEqual(len(response.context["expenses"]), 0)
        self.assertContains(response, "No expenses match these filters")

    def test_pagination_links_preserve_the_filters(self):
        for _ in range(30):
            Expense.objects.create(
                user=self.alice,
                category=self.food,
                amount=1,
                spent_on=date(2026, 9, 10),
                note="bulk",
            )

        response = self._get(start="2026-09-01", end="2026-09-30", search="bulk")

        # Dropping the query string on page 2 is the classic filtering bug:
        # the user pages into unfiltered data without noticing.
        self.assertContains(response, "search=bulk")
        self.assertContains(response, "page=2")
