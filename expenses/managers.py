from decimal import Decimal

from django.db import models
from django.db.models import Count, DecimalField, F, Sum, Value
from django.db.models.functions import Abs, Coalesce


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

    def unbalanced(self):
        """Itemised expenses whose items and misc do not sum to their amount within tolerance.

        Rows written before phase 8 -- or by the admin, a data migration, or a shell
        session -- never met that rule. An invariant a database cannot hold is an
        invariant that needs auditing, which is the honest cost of moving it into the form.

        ``F("amount")`` is what makes this a column-to-column comparison.
        Without it, ``exclude(items_total=self.amount)`` would compare
        against a Python attribute that does not exist on a queryset; the
        value has to be named as a database reference so the database does
        the comparing, row by row.
        """
        from .models import ROUNDING_TOLERANCE

        # Filtering on the annotation, not on the relation again.
        # ``.filter(items__isnull=False)`` would look equivalent and is not:
        # Django adds a second join for a filter that re-traverses a
        # relation already used by annotate(), which both multiplies rows
        # and stops the isnull test meaning what it reads as. Sum over no
        # rows is NULL, so the annotation already answers "is it itemised".
        diff_expr = Abs(
            F("amount") - F("items_total") - Coalesce(F("misc_amount"), Value(Decimal("0"))),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )
        return (
            self.annotate(items_total=Sum("items__amount"))
            .filter(items_total__isnull=False)
            .annotate(diff=diff_expr)
            .filter(diff__gte=ROUNDING_TOLERANCE)
        )

    def biggest(self):
        """The single largest expense, or None.

        select_related avoids a second query when the caller reads
        expense.category.name, which every caller does.
        """
        return self.select_related("category").order_by("-amount", "-spent_on").first()
