"""The aggregation layer, tested without a request.

That is the point of it: phase 6's digest runs in a Celery task, so these
must work standing alone.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from expenses.models import Category, Expense
from expenses.summaries import (
    is_whole_month,
    month_bounds,
    previous_period,
    summarise,
)

User = get_user_model()


class PeriodMathTests(TestCase):
    """Pure date arithmetic — no database needed."""

    def test_month_bounds_handles_31_day_month(self):
        self.assertEqual(month_bounds(date(2026, 1, 15)), (date(2026, 1, 1), date(2026, 1, 31)))

    def test_month_bounds_handles_february_in_a_leap_year(self):
        self.assertEqual(month_bounds(date(2028, 2, 10)), (date(2028, 2, 1), date(2028, 2, 29)))

    def test_month_bounds_handles_february_in_a_common_year(self):
        self.assertEqual(month_bounds(date(2026, 2, 10)), (date(2026, 2, 1), date(2026, 2, 28)))

    def test_is_whole_month(self):
        self.assertTrue(is_whole_month(date(2026, 9, 1), date(2026, 9, 30)))
        self.assertFalse(is_whole_month(date(2026, 9, 1), date(2026, 9, 29)))
        self.assertFalse(is_whole_month(date(2026, 9, 2), date(2026, 9, 30)))

    def test_whole_month_compares_against_the_whole_previous_month(self):
        # September has 30 days and August 31, so a naive "same number of
        # days" rule would compare against 2-31 August and silently drop a
        # day's spending.
        self.assertEqual(
            previous_period(date(2026, 9, 1), date(2026, 9, 30)),
            (date(2026, 8, 1), date(2026, 8, 31)),
        )

    def test_march_compares_against_february(self):
        self.assertEqual(
            previous_period(date(2026, 3, 1), date(2026, 3, 31)),
            (date(2026, 2, 1), date(2026, 2, 28)),
        )

    def test_january_compares_against_december_of_the_previous_year(self):
        self.assertEqual(
            previous_period(date(2026, 1, 1), date(2026, 1, 31)),
            (date(2025, 12, 1), date(2025, 12, 31)),
        )

    def test_arbitrary_range_compares_against_an_equally_long_window(self):
        # A 7-day range (10-16 Sep) compares against 3-9 Sep.
        self.assertEqual(
            previous_period(date(2026, 9, 10), date(2026, 9, 16)),
            (date(2026, 9, 3), date(2026, 9, 9)),
        )

    def test_single_day_compares_against_the_day_before(self):
        self.assertEqual(
            previous_period(date(2026, 9, 10), date(2026, 9, 10)),
            (date(2026, 9, 9), date(2026, 9, 9)),
        )


class SummariseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")

        cls.rent = Category.objects.create(user=cls.alice, name="Rent")
        cls.food = Category.objects.create(user=cls.alice, name="Food")
        cls.bob_cat = Category.objects.create(user=cls.bob, name="Rent")

        # September: 8400 rent + (200 + 300) food = 8900
        Expense.objects.create(
            user=cls.alice, category=cls.rent, amount=Decimal("8400"), spent_on=date(2026, 9, 3)
        )
        Expense.objects.create(
            user=cls.alice, category=cls.food, amount=Decimal("200"), spent_on=date(2026, 9, 1)
        )
        Expense.objects.create(
            user=cls.alice, category=cls.food, amount=Decimal("300"), spent_on=date(2026, 9, 30)
        )
        # August: 1000
        Expense.objects.create(
            user=cls.alice, category=cls.food, amount=Decimal("1000"), spent_on=date(2026, 8, 15)
        )
        # Bob's, which must never appear in Alice's numbers.
        Expense.objects.create(
            user=cls.bob, category=cls.bob_cat, amount=Decimal("99999"), spent_on=date(2026, 9, 5)
        )

    def _september(self):
        return summarise(self.alice, date(2026, 9, 1), date(2026, 9, 30))

    def test_total_covers_only_the_range(self):
        self.assertEqual(self._september().total, Decimal("8900"))

    def test_range_boundaries_are_inclusive(self):
        # Expenses on the 1st and the 30th must both count.
        self.assertEqual(self._september().count, 3)

    def test_other_users_spending_is_excluded(self):
        # Bob spent 99999 in the same range through a category with the
        # same name. Neither the total nor the breakdown may show it.
        summary = self._september()

        self.assertEqual(summary.total, Decimal("8900"))
        self.assertNotIn(self.bob_cat.id, [row["category_id"] for row in summary.by_category])

    def test_by_category_is_grouped_and_ordered_by_size(self):
        rows = self._september().by_category

        self.assertEqual(
            [(r["category__name"], r["total"], r["count"]) for r in rows],
            [("Rent", Decimal("8400"), 1), ("Food", Decimal("500"), 2)],
        )

    def test_biggest_expense_is_found(self):
        self.assertEqual(self._september().biggest.amount, Decimal("8400"))

    def test_empty_period_is_a_normal_state(self):
        summary = summarise(self.alice, date(2020, 1, 1), date(2020, 1, 31))

        self.assertEqual(summary.total, Decimal("0"))
        self.assertEqual(summary.count, 0)
        self.assertIsNone(summary.biggest)
        self.assertEqual(summary.by_category, [])
        self.assertEqual(summary.average_per_expense, Decimal("0"))
        self.assertEqual(summary.share_of_total(Decimal("10")), Decimal("0"))

    def test_change_from_previous_period(self):
        september = self._september()
        august = summarise(self.alice, date(2026, 8, 1), date(2026, 8, 31))

        # 1000 -> 8900 is +790%
        self.assertEqual(september.change_from(august), Decimal("790"))

    def test_change_is_none_when_there_is_nothing_to_compare(self):
        # "Up 100% from zero" is meaningless; None distinguishes "no
        # comparison possible" from "no change".
        september = self._september()
        empty = summarise(self.alice, date(2020, 1, 1), date(2020, 1, 31))

        self.assertIsNone(september.change_from(empty))

    def test_share_of_total(self):
        summary = self._september()

        self.assertEqual(round(summary.share_of_total(Decimal("8900")), 2), Decimal("100.00"))

    def test_summarise_costs_three_queries(self):
        # Aggregates, per-category grouping, biggest. Flat regardless of how
        # many expenses or categories exist — pinned so a future change that
        # loops in Python fails loudly.
        with self.assertNumQueries(3):
            summarise(self.alice, date(2026, 9, 1), date(2026, 9, 30))

    def test_biggest_does_not_query_again_for_its_category(self):
        summary = self._september()

        with self.assertNumQueries(0):
            _ = summary.biggest.category.name
