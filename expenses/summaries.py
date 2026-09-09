"""Period summaries, shared by the dashboard and (in phase 6) the digest email.

Kept out of views.py deliberately. The monthly digest task needs exactly
this computation with no request in sight, so it lives somewhere both a
view and a Celery task can import.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Sum

from .models import Expense


def month_bounds(day: date) -> tuple[date, date]:
    """First and last day of the calendar month containing `day`."""
    last = calendar.monthrange(day.year, day.month)[1]
    return day.replace(day=1), day.replace(day=last)


def is_whole_month(start: date, end: date) -> bool:
    return (start, end) == month_bounds(start)


def previous_period(start: date, end: date) -> tuple[date, date]:
    """The window to compare a range against.

    A whole calendar month compares against the whole previous calendar
    month, because that is what people mean by "versus last month" — and
    what the digest email needs.

    Any other range compares against the equally long window ending the day
    before it starts. Comparing a 9-day range against a full month would
    make every number look like a collapse.
    """
    previous_end = start - timedelta(days=1)

    if is_whole_month(start, end):
        return month_bounds(previous_end)

    return previous_end - (end - start), previous_end


@dataclass(frozen=True)
class PeriodSummary:
    """What was spent in one date range."""

    start: date
    end: date
    total: Decimal
    count: int
    biggest: Expense | None
    by_category: list[dict]

    @property
    def average_per_expense(self) -> Decimal:
        if not self.count:
            return Decimal("0")
        return self.total / self.count

    def share_of_total(self, amount: Decimal) -> Decimal:
        """That amount as a percentage of the period total.

        Guarded because a period with no spending would otherwise divide by
        zero — an empty dashboard is a normal state, not an error.
        """
        if not self.total:
            return Decimal("0")
        return (amount / self.total) * 100

    def change_from(self, previous: "PeriodSummary") -> Decimal | None:
        """Percentage change against an earlier period.

        Returns None rather than 0 or infinity when the earlier period had
        no spending: "up 100%" from nothing is misleading, and there is a
        real difference between "no change" and "nothing to compare".
        """
        if not previous.total:
            return None
        return ((self.total - previous.total) / previous.total) * 100


def summarise(user, start: date, end: date) -> PeriodSummary:
    """Everything the dashboard and the digest need, for one date range.

    Three queries: the aggregate totals, the per-category grouping, and the
    single biggest expense. Deliberately not one clever query — these are
    different shapes, and three indexed reads are cheaper than the joins
    needed to force them together.
    """
    expenses = Expense.objects.for_user(user).in_range(start, end)

    aggregates = expenses.aggregate(total=Sum("amount"), count=Count("id"))

    return PeriodSummary(
        start=start,
        end=end,
        total=aggregates["total"] or Decimal("0"),
        count=aggregates["count"],
        biggest=expenses.biggest(),
        by_category=list(expenses.by_category()),
    )
