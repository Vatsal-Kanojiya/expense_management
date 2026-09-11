from decimal import Decimal

from django.db import models
from django.db.models import Count, Sum


class ExpenseQuerySet(models.QuerySet):
    """Chainable query building blocks for Expense.

    These live on the queryset rather than in a view for one concrete
    reason: phase 6's monthly digest runs inside a Celery task, where there
    is no request and no view. A queryset method is callable from a view, a
    task, a management command and the shell alike.

    Each method returns a queryset, so they compose:

        Expense.objects.for_user(u).in_range(start, end).by_category()
    """

    def for_user(self, user):
        return self.filter(user=user)

    def in_range(self, start, end):
        # Inclusive at both ends: a range labelled 1–30 September should
        # contain expenses on the 30th.
        return self.filter(spent_on__gte=start, spent_on__lte=end)

    def total(self) -> Decimal:
        """Sum of this queryset's amounts, safe across joins.

        The obvious ``self.aggregate(Sum("amount"))`` is wrong the moment a
        filter crosses a multi-valued relation. Searching items or
        participants joins one expense to several child rows, and the
        aggregate then counts that expense once per match -- a 900 expense
        with two matching items reports 1800.

        ``.distinct()`` does not fix it. DISTINCT removes duplicate rows
        from a result set; the aggregate has already consumed them.

        Summing over the distinct set of primary keys does fix it, at the
        cost of a subquery. ``order_by()`` clears the model's default
        ordering, which some databases reject inside a subquery.
        """
        pks = self.order_by().values("pk")
        totals = self.model._default_manager.filter(pk__in=pks).aggregate(total=Sum("amount"))

        # Sum() returns None over an empty queryset, which would propagate a
        # None into arithmetic and templates. Coerce it once, here.
        return totals["total"] or Decimal("0")

    def by_category(self):
        """Per-category totals, largest first.

        values() before annotate() is what makes this a GROUP BY on the
        category rather than one row per expense — the ordering of those two
        calls changes the SQL, which is the classic annotate() gotcha.

        Grouping on the FK id as well as the name keeps two categories that
        share a name (different users) from collapsing into one row.
        """
        return (
            self.values("category_id", "category__name")
            .annotate(total=Sum("amount"), count=Count("id"))
            .order_by("-total")
        )

    def biggest(self):
        """The single largest expense, or None.

        select_related avoids a second query when the caller reads
        expense.category.name, which every caller does.
        """
        return self.select_related("category").order_by("-amount", "-spent_on").first()
