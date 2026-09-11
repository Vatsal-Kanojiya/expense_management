"""What the database guarantees about a split expense.

Companion to test_splitting.py, which covers the arithmetic. This file is
about the constraints, the delete policies, and the one asymmetry between a
generated join table and an explicit through model.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from expenses.models import Category, Expense, ExpenseItem, ItemShare, Participant

User = get_user_model()


class SplitModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")
        cls.category = Category.objects.create(user=cls.alice, name="Food")
        cls.expense = Expense.objects.create(
            user=cls.alice,
            category=cls.category,
            amount=Decimal("900.00"),
            spent_on=date(2026, 1, 15),
        )
        cls.rahul = Participant.objects.create(user=cls.alice, name="Rahul")

    def test_participant_names_are_unique_per_user(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Participant.objects.create(user=self.alice, name="Rahul")

    def test_two_users_may_both_know_a_rahul(self):
        # The rows never meet. This is the whole reason participants are not
        # User objects: no invitations, no linking, no shared identity.
        Participant.objects.create(user=self.bob, name="Rahul")

        self.assertEqual(Participant.objects.filter(name="Rahul").count(), 2)

    def test_an_item_must_cost_something(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExpenseItem.objects.create(expense=self.expense, name="Free", amount=Decimal("0"))

    def test_a_participant_cannot_share_one_item_twice(self):
        item = ExpenseItem.objects.create(
            expense=self.expense, name="Pizza", amount=Decimal("300.00")
        )
        ItemShare.objects.create(item=item, participant=self.rahul)

        with self.assertRaises(IntegrityError), transaction.atomic():
            ItemShare.objects.create(item=item, participant=self.rahul, weight=2)

    def test_a_share_weight_must_be_positive(self):
        item = ExpenseItem.objects.create(
            expense=self.expense, name="Pizza", amount=Decimal("300.00")
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            ItemShare.objects.create(item=item, participant=self.rahul, weight=0)

    def test_deleting_an_expense_takes_its_items_and_shares(self):
        item = ExpenseItem.objects.create(
            expense=self.expense, name="Pizza", amount=Decimal("300.00")
        )
        ItemShare.objects.create(item=item, participant=self.rahul)

        self.expense.delete()

        self.assertEqual(ExpenseItem.objects.count(), 0)
        self.assertEqual(ItemShare.objects.count(), 0)

    def test_a_participant_on_an_item_cannot_be_deleted(self):
        item = ExpenseItem.objects.create(
            expense=self.expense, name="Pizza", amount=Decimal("300.00")
        )
        ItemShare.objects.create(item=item, participant=self.rahul)

        # PROTECT, matching Expense.category. Removing someone from a past
        # bill would leave that item charged to nobody.
        with self.assertRaises(ProtectedError):
            self.rahul.delete()

    def test_the_generated_join_table_cascades_instead(self):
        """The asymmetry worth knowing, asserted rather than assumed.

        ``Expense.participants`` has no through model, so Django generates
        its join table and hard-codes CASCADE. There is no on_delete to
        pass. Deleting a participant silently drops the even-split rows
        while ItemShare above refuses. The moment a relationship needs its
        own delete policy, it has to become a real model.
        """
        priya = Participant.objects.create(user=self.alice, name="Priya")
        self.expense.participants.add(priya)

        priya.delete()

        self.assertEqual(self.expense.participants.count(), 0)

    def test_split_mode_is_derived_not_stored(self):
        # Nothing records "this is an even split". The rows say so.
        self.assertFalse(self.expense.items.exists())
        self.assertFalse(self.expense.participants.exists())

        self.expense.participants.add(self.rahul)

        self.assertTrue(self.expense.participants.exists())
