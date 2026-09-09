"""Model-level tests: what the *database* guarantees.

These deliberately bypass forms and views and hit the ORM directly. The
point is to prove the constraints hold even when application code is
wrong or absent — a form check can be skipped, a DB constraint cannot.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from expenses.models import Category, Expense

User = get_user_model()


class CategoryConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # setUpTestData runs once per class and its data is rolled back
        # between tests, unlike setUp which re-creates rows every method.
        cls.alice = User.objects.create_user("alice", password="pw12345!")
        cls.bob = User.objects.create_user("bob", password="pw12345!")

    def test_same_name_allowed_for_different_users(self):
        Category.objects.create(user=self.alice, name="Food")
        Category.objects.create(user=self.bob, name="Food")

        self.assertEqual(Category.objects.filter(name="Food").count(), 2)

    def test_duplicate_name_for_same_user_is_rejected(self):
        Category.objects.create(user=self.alice, name="Food")

        # The atomic() block matters: an IntegrityError breaks the surrounding
        # transaction, and without its own savepoint every later query in this
        # test would fail with TransactionManagementError.
        with self.assertRaises(IntegrityError), transaction.atomic():
            Category.objects.create(user=self.alice, name="Food")

    def test_db_uniqueness_is_case_sensitive(self):
        """Documents current behaviour, which is NOT what the form enforces.

        UniqueConstraint(user, name) is an exact match, while
        CategoryForm.clean_name uses __iexact. So the form is stricter than
        the database: "food" is refused through the app but accepted by the
        ORM and by the admin, which does not use our form. See BUILD_LOG
        known issues.
        """
        Category.objects.create(user=self.alice, name="Food")
        Category.objects.create(user=self.alice, name="food")

        self.assertEqual(Category.objects.filter(user=self.alice).count(), 2)

    def test_deleting_user_cascades_to_categories(self):
        Category.objects.create(user=self.alice, name="Food")

        self.alice.delete()

        self.assertEqual(Category.objects.count(), 0)

    def test_ordering_is_by_name(self):
        Category.objects.create(user=self.alice, name="Travel")
        Category.objects.create(user=self.alice, name="食費")
        Category.objects.create(user=self.alice, name="Food")

        self.assertEqual(
            [c.name for c in Category.objects.filter(user=self.alice)],
            ["Food", "Travel", "食費"],
        )


class ExpenseConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw12345!")
        cls.category = Category.objects.create(user=cls.alice, name="Food")

    def _expense(self, **overrides):
        defaults = {
            "user": self.alice,
            "category": self.category,
            "amount": Decimal("10.00"),
            "spent_on": date(2026, 9, 1),
        }
        return Expense.objects.create(**{**defaults, **overrides})

    def test_positive_amount_is_allowed(self):
        expense = self._expense(amount=Decimal("0.01"))

        self.assertEqual(Expense.objects.count(), 1)
        self.assertEqual(expense.amount, Decimal("0.01"))

    def test_zero_amount_is_rejected(self):
        # CheckConstraint uses amount > 0, so zero must fail too. Boundary
        # cases are where off-by-one constraint bugs live.
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._expense(amount=Decimal("0.00"))

    def test_negative_amount_is_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._expense(amount=Decimal("-1.00"))

    def test_category_with_expenses_cannot_be_deleted(self):
        self._expense()

        # on_delete=PROTECT: spending history must not vanish because a
        # category was tidied up.
        with self.assertRaises(ProtectedError):
            self.category.delete()

        self.assertEqual(Expense.objects.count(), 1)

    def test_category_without_expenses_can_be_deleted(self):
        empty = Category.objects.create(user=self.alice, name="Unused")

        empty.delete()

        self.assertFalse(Category.objects.filter(pk=empty.pk).exists())

    def test_deleting_user_with_expenses_currently_fails(self):
        """KNOWN BUG, documented rather than asserted as desirable.

        Expense.category is PROTECT while both Expense.user and
        Category.user are CASCADE. Deleting a user makes the collector
        cascade to their categories, which are still referenced by their
        expenses — so PROTECT fires, even though those same expenses would
        have cascaded away too. Django refuses rather than ordering the
        deletes itself.

        Net effect: account deletion is broken. See BUILD_LOG known issues.
        This test will fail once that is fixed, which is the intent — it is
        a tripwire, not an endorsement.
        """
        self._expense()

        with self.assertRaises(ProtectedError):
            self.alice.delete()

    def test_deleting_user_works_when_expenses_removed_first(self):
        """The manual workaround, and the shape any real fix must take."""
        self._expense()

        Expense.objects.filter(user=self.alice).delete()
        Category.objects.filter(user=self.alice).delete()
        self.alice.delete()

        self.assertEqual(Expense.objects.count(), 0)
        self.assertEqual(Category.objects.count(), 0)

    def test_deleting_user_without_expenses_cascades(self):
        self.alice.delete()

        self.assertEqual(Category.objects.count(), 0)

    def test_ordering_is_newest_spend_first(self):
        older = self._expense(spent_on=date(2026, 8, 1))
        newer = self._expense(spent_on=date(2026, 9, 1))

        self.assertEqual(list(Expense.objects.all()), [newer, older])
