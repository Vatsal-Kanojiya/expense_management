# Create your models here.
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
