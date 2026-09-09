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
