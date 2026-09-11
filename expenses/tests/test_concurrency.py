"""The race, proved rather than asserted.

These use TransactionTestCase, not TestCase. TestCase wraps each test in a
transaction and rolls it back, which means a second thread could never see
the first thread's committed rows -- the very thing under test. That is the
same trap phase 6 hit with the digest command, in a different costume.

The locking tests are Postgres-only and skipped elsewhere, deliberately.
select_for_update is a no-op on SQLite, which locks the whole database
rather than individual rows, so running them there would report a pass that
means nothing.
"""

import threading
import unittest
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import TestCase, TransactionTestCase

from expenses.models import Category, Expense, Participant, Settlement
from expenses.settlements import outstanding, settle_up

User = get_user_model()

postgres_only = unittest.skipUnless(
    connection.vendor == "postgresql",
    "select_for_update is a no-op on SQLite, which locks the whole database",
)


def _fixture():
    """One user who is owed 150 by one participant."""
    alice = User.objects.create_user("alice", email="alice@example.com", password="pw12345!")
    category = Category.objects.create(user=alice, name="Food")
    rahul = Participant.objects.create(user=alice, name="Rahul")
    expense = Expense.objects.create(
        user=alice, category=category, amount=Decimal("300.00"), spent_on=date.today()
    )
    expense.participants.add(rahul)
    return alice, rahul


class SettleUpTests(TestCase):
    """Behaviour, without the concurrency."""

    def setUp(self):
        self.alice, self.rahul = _fixture()

    def test_settling_records_the_outstanding_amount(self):
        settlement = settle_up(self.alice, self.rahul.pk)

        self.assertEqual(settlement.amount, Decimal("150.00"))

    def test_settling_twice_records_nothing_the_second_time(self):
        settle_up(self.alice, self.rahul.pk)

        self.assertIsNone(settle_up(self.alice, self.rahul.pk))
        self.assertEqual(Settlement.objects.count(), 1)

    def test_outstanding_drops_to_zero(self):
        settle_up(self.alice, self.rahul.pk)

        self.assertEqual(outstanding(self.alice, self.rahul), Decimal("0"))

    def test_a_new_expense_reopens_the_balance(self):
        settle_up(self.alice, self.rahul.pk)
        expense = Expense.objects.create(
            user=self.alice,
            category=Category.objects.get(user=self.alice),
            amount=Decimal("100.00"),
            spent_on=date.today(),
        )
        expense.participants.add(self.rahul)

        self.assertEqual(outstanding(self.alice, self.rahul), Decimal("50.00"))

    def test_another_users_participant_cannot_be_settled(self):
        bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")

        with self.assertRaises(Participant.DoesNotExist):
            settle_up(bob, self.rahul.pk)


@postgres_only
class SettleUpRaceTests(TransactionTestCase):
    """Two settlements at the same instant."""

    def setUp(self):
        self.alice, self.rahul = _fixture()

    def _settle_in_thread(self, results, index):
        try:
            settlement = settle_up(self.alice, self.rahul.pk)
            results[index] = settlement.amount if settlement else None
        finally:
            # Each thread gets its own connection. Left open, the test
            # database cannot be torn down.
            connections.close_all()

    def test_two_concurrent_settlements_produce_one_row(self):
        """The lost update, prevented.

        Without select_for_update both threads read 150 outstanding and
        both write a settlement, so a 150 debt is repaid 300. No unique
        constraint could catch it: two genuine settlements of the same
        amount on the same day are perfectly legal.

        With the lock, the second thread blocks on SELECT ... FOR UPDATE
        until the first commits, then reads a balance that already includes
        it and writes nothing.
        """
        results = [None, None]
        threads = [
            threading.Thread(target=self._settle_in_thread, args=(results, index))
            for index in range(2)
        ]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(Settlement.objects.count(), 1)
        self.assertEqual(Settlement.objects.get().amount, Decimal("150.00"))
        # Exactly one thread settled; the other found nothing to do.
        self.assertEqual(sorted(results, key=lambda v: v is None), [Decimal("150.00"), None])

    def test_the_total_repaid_never_exceeds_the_debt(self):
        results = [None, None]
        threads = [
            threading.Thread(target=self._settle_in_thread, args=(results, index))
            for index in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        repaid = sum(s.amount for s in Settlement.objects.all())

        self.assertEqual(repaid, Decimal("150.00"))
        self.assertEqual(outstanding(self.alice, self.rahul), Decimal("0"))


class NestedAtomicTests(TestCase):
    """Savepoints, and the two ways people get nested atomic wrong."""

    def setUp(self):
        self.alice, self.rahul = _fixture()

    def test_an_inner_block_rolls_back_alone(self):
        from django.db import transaction

        with transaction.atomic():
            Settlement.objects.create(
                user=self.alice, participant=self.rahul, amount=Decimal("10.00")
            )

            # The inner atomic() is a SAVEPOINT, not a second transaction.
            # Rolling it back discards only what happened inside it.
            try:
                with transaction.atomic():
                    Settlement.objects.create(
                        user=self.alice, participant=self.rahul, amount=Decimal("20.00")
                    )
                    raise ValueError("something went wrong")
            except ValueError:
                pass

        self.assertEqual(Settlement.objects.count(), 1)
        self.assertEqual(Settlement.objects.get().amount, Decimal("10.00"))

    def test_a_caught_database_error_poisons_the_block_without_a_savepoint(self):
        """The trap, stated correctly.

        A savepoint is what makes a caught error survivable. An inner
        atomic() creates one, so catching the exception outside that block
        is fine -- the savepoint has already rolled back cleanly.

        What is not fine is catching a *database* error with no savepoint
        between it and the outer block. The connection is left in a failed
        transaction, and Django refuses every further query in it rather
        than letting you build on broken state.

        This is why every constraint test in this project reads
        ``with self.assertRaises(IntegrityError), transaction.atomic():``
        -- the atomic() is the savepoint, not decoration.
        """
        from django.db import IntegrityError, transaction
        from django.db.transaction import TransactionManagementError

        with self.assertRaises(TransactionManagementError), transaction.atomic():
            try:
                # Violates settlement_amount_positive.
                Settlement.objects.create(
                    user=self.alice, participant=self.rahul, amount=Decimal("-1.00")
                )
            except IntegrityError:
                pass

            Settlement.objects.count()

    def test_the_same_error_is_survivable_inside_a_savepoint(self):
        from django.db import IntegrityError, transaction

        with transaction.atomic():
            with self.assertRaises(IntegrityError), transaction.atomic():
                Settlement.objects.create(
                    user=self.alice, participant=self.rahul, amount=Decimal("-1.00")
                )

            # The savepoint rolled back; the outer transaction is healthy.
            Settlement.objects.create(
                user=self.alice, participant=self.rahul, amount=Decimal("10.00")
            )

        self.assertEqual(Settlement.objects.count(), 1)

    def test_settle_up_is_atomic_end_to_end(self):
        # The decorator on settle_up covers the read and the write together.
        # Without it the lock would be released the instant the SELECT
        # returned, which is before the settlement is written.
        settlement = settle_up(self.alice, self.rahul.pk)

        self.assertEqual(Settlement.objects.get(), settlement)
