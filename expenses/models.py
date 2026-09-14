# Create your models here.
from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

from .managers import ExpenseQuerySet


class Category(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="categories",
    )
    name = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"
        constraints = [
            # Lower(), so the database finally agrees with the form.
            #
            # clean_name has always rejected a duplicate case-insensitively
            # while the constraint matched exactly, which meant the admin,
            # the shell and the API could each create "Food" alongside
            # "food" and the app could not. Known issue 11 from session 3.
            #
            # This is a functional index. Postgres and SQLite both support
            # one; MySQL before 8.0.13 does not, which is the usual reason
            # people reach for a stored lowercase column instead.
            models.UniqueConstraint(
                Lower("name"),
                "user",
                name="uniq_category_name_per_user_ci",
            )
        ]

    def __str__(self):
        return self.name


class Expense(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="expenses",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="expenses",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    spent_on = models.DateField()
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # An even split. Forward string reference because Participant is defined
    # below; Django resolves these when the app registry loads.
    #
    # There is no split_mode field on purpose. The mode is derivable: items
    # exist -> itemised, else participants exist -> even split, else it is
    # yours alone. A stored mode would be a second source of truth that can
    # disagree with the rows it describes.
    participants = models.ManyToManyField(
        "Participant",
        blank=True,
        related_name="shared_expenses",
    )

    # as_manager() turns the queryset's methods into manager methods, so
    # Expense.objects.for_user(u) works as well as
    # Expense.objects.filter(...).for_user(u). Managers do not affect the
    # schema, so this needs no migration.
    objects = ExpenseQuerySet.as_manager()

    class Meta:
        ordering = ["-spent_on", "-id"]
        indexes = [
            models.Index(fields=["user", "spent_on"]),
            # Column order is the whole design of a composite index.
            # Equality columns first, the range column last: the list view
            # filters user = ? AND category = ? AND spent_on BETWEEN ? AND ?,
            # and an index can only use columns up to and including the
            # first range predicate. Put spent_on first and the category
            # equality cannot be used at all.
            models.Index(
                fields=["user", "category", "spent_on"],
                name="expense_user_cat_date",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="expense_amount_positive",
            )
        ]

    def __str__(self):
        return f"{self.amount} on {self.spent_on}"

    def items_total(self):
        """Sum of the line items, or None when there are none.

        Reads the prefetched cache like ``shared_with`` below, so callers
        that already loaded the items pay nothing for asking.
        """
        items = list(self.items.all())

        if not items:
            return None

        return sum((item.amount for item in items), Decimal("0"))

    def is_balanced(self):
        """Whether this expense's split adds up.

        The rule used to be a hard validation error: items that did not sum
        to the amount could not be saved at all. That cost more than it
        bought -- a long form was refused wholesale over one wrong figure,
        and a refresh lost the lot. The record is now allowed to exist in a
        state the split cannot be computed from, and this is the predicate
        that says so. ``balances`` skips an expense that fails it, so a
        half-entered split is never silently counted as a whole one.

        True when there is nothing to reconcile, which is the common case.
        """
        total = self.items_total()

        return total is None or total == self.amount

    def shared_with(self):
        """Every participant on this expense, however they got there.

        Reads only prefetched caches -- ``.all()`` on an already-prefetched
        relation does not hit the database. Without the prefetch in
        ExpenseListView this is two levels of N+1 per row, which is exactly
        why the query count is pinned in the tests.
        """
        names = {participant.name for participant in self.participants.all()}

        for item in self.items.all():
            for share in item.shares.all():
                names.add(share.participant.name)

        return sorted(names)


def export_upload_path(instance, filename):
    """Unguessable path for a generated export.

    The download view checks ownership, so this is defence in depth: if the
    file is ever served directly by nginx or copied to a bucket, the path
    itself must not be enumerable.
    """
    return f"exports/{instance.user_id}/{uuid4().hex}.csv"


class ExportJob(models.Model):
    """A user's request for a CSV of their expenses.

    The row exists so the user can be shown progress and given a stable
    link. The task updates it; nothing else writes status.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETE = "complete", "Complete"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="export_jobs",
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    start = models.DateField()
    end = models.DateField()
    file = models.FileField(upload_to=export_upload_path, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]
        indexes = [models.Index(fields=["user", "-requested_at"])]

    def __str__(self):
        return f"Export {self.pk} ({self.status})"


class MonthlyDigest(models.Model):
    """Record that a digest was sent, and the guard against sending twice.

    The unique constraint on (user, month) is the whole point. Beat or cron
    can fire twice after a restart, and a retried task runs again by design.
    Claiming this row before sending is what makes a second run a no-op.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="monthly_digests",
    )
    # Always the first day of the month it covers, so equality works.
    month = models.DateField()
    total = models.DecimalField(max_digits=12, decimal_places=2)
    expense_count = models.PositiveIntegerField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-month"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "month"],
                name="uniq_digest_per_user_month",
            )
        ]

    def __str__(self):
        return f"Digest for {self.user} — {self.month:%B %Y}"


class Participant(models.Model):
    """Someone an expense is shared with.

    Deliberately *not* a User. Participants are plain rows owned by one user,
    so there are no invitations, no account linking and no second tenancy
    model to reason about. "Rahul" in your list and "Rahul" in mine are
    different rows that never meet.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="participants",
    )
    name = models.CharField(max_length=60)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            # Same correction as Category above, applied before the same
            # mismatch had time to become a second known issue.
            models.UniqueConstraint(
                Lower("name"),
                "user",
                name="uniq_participant_name_per_user_ci",
            )
        ]

    def __str__(self):
        return self.name


class ExpenseItem(models.Model):
    """One line on a split bill.

    The invariant that matters is *not* expressible here: the items of an
    expense must sum to that expense's amount. A CheckConstraint sees a
    single row and cannot reach across siblings, so that rule lives in the
    formset's clean() and is held by a transaction. Knowing which invariants
    a database can carry, and which it cannot, is the point of this model.
    """

    expense = models.ForeignKey(
        Expense,
        on_delete=models.CASCADE,
        related_name="items",
    )
    name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="item_amount_positive",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.amount})"


class ItemShare(models.Model):
    """Who consumed one line item, and in what proportion.

    This is the explicit through model, and the contrast with
    ``Expense.participants`` above is the lesson. That field's join table is
    generated by Django, carries no columns of its own, and **cascades on
    delete with no way to change it**. The moment a relationship needs a
    payload -- here, a weight -- or a delete policy of its own, it has to
    become a real model.

    Weights, not amounts. Storing each share as money would mean re-deriving
    every sibling row whenever one changed, and would let the shares drift
    away from the item total. Weights cannot drift: the split is computed at
    read time, and the remainder is allocated deterministically so the parts
    always reconstitute the whole.
    """

    item = models.ForeignKey(
        ExpenseItem,
        on_delete=models.CASCADE,
        related_name="shares",
    )
    # PROTECT, matching Expense.category. Deleting someone who appears on a
    # past bill would silently rewrite history and leave items charged to
    # nobody. This extends known issue 10: account deletion needs an ordered
    # delete, and now so does participant deletion.
    participant = models.ForeignKey(
        Participant,
        on_delete=models.PROTECT,
        related_name="item_shares",
    )
    weight = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["item", "participant"],
                name="uniq_share_per_item_participant",
            ),
            models.CheckConstraint(
                condition=models.Q(weight__gt=0),
                name="share_weight_positive",
            ),
        ]

    def __str__(self):
        return f"{self.participant} x{self.weight}"


class Settlement(models.Model):
    """Money a participant has paid back.

    A balance is "what they owe" minus "what they have repaid". Storing the
    repayments rather than a running balance column is deliberate: a
    denormalised total is a second source of truth that drifts, and the
    expenses it derives from are already immutable history.

    The cost is that settling is a read-then-write, which is exactly the
    shape that races. See ``settlements.settle_up``.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="settlements",
    )
    participant = models.ForeignKey(
        Participant,
        on_delete=models.CASCADE,
        related_name="settlements",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    settled_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-settled_at", "-id"]
        indexes = [models.Index(fields=["user", "participant"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="settlement_amount_positive",
            )
        ]

    def __str__(self):
        return f"{self.participant} settled {self.amount}"
