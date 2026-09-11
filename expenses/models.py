# Create your models here.
from uuid import uuid4

from django.conf import settings
from django.db import models

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
            models.UniqueConstraint(
                fields=["user", "name"],
                name="uniq_category_per_user",
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
        indexes = [models.Index(fields=["user", "spent_on"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="expense_amount_positive",
            )
        ]

    def __str__(self):
        return f"{self.amount} on {self.spent_on}"

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
            models.UniqueConstraint(
                fields=["user", "name"],
                name="uniq_participant_per_user",
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
