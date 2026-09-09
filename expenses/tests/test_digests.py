"""The monthly digest command.

Idempotency is the point of these. A scheduled job WILL run twice — cron
fires again after a restart, someone reruns it by hand, two servers both
have the crontab — and the only acceptable outcome is that the second run
does nothing.
"""

from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, TransactionTestCase

from expenses.models import Category, Expense, MonthlyDigest

User = get_user_model()


class SendMonthlyDigestsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")

        cls.food = Category.objects.create(user=cls.alice, name="Food")
        cls.rent = Category.objects.create(user=cls.alice, name="Rent")
        bob_food = Category.objects.create(user=cls.bob, name="Food")

        # Alice, August 2026: 8400 + 600 = 9000
        Expense.objects.create(
            user=cls.alice, category=cls.rent, amount=Decimal("8400"), spent_on=date(2026, 8, 3)
        )
        Expense.objects.create(
            user=cls.alice, category=cls.food, amount=Decimal("600"), spent_on=date(2026, 8, 20)
        )
        # Alice, July 2026: 1000, so August can be compared against it.
        Expense.objects.create(
            user=cls.alice, category=cls.food, amount=Decimal("1000"), spent_on=date(2026, 7, 5)
        )
        # Bob, August: 250
        Expense.objects.create(
            user=cls.bob, category=bob_food, amount=Decimal("250"), spent_on=date(2026, 8, 9)
        )

    def _run(self, **options):
        out = StringIO()
        call_command("send_monthly_digests", stdout=out, stderr=StringIO(), **options)
        return out.getvalue()

    def _august(self, **options):
        return self._run(month="2026-08", **options)

    # ---- Core behaviour ------------------------------------------------

    def test_sends_one_email_per_user_with_spending(self):
        mail.outbox = []

        self._august()

        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox),
            ["alice@example.com", "bob@example.com"],
        )

    def test_email_contains_the_right_numbers(self):
        mail.outbox = []

        self._august(user="alice")

        body = mail.outbox[0].body
        self.assertIn("August 2026", mail.outbox[0].subject)
        self.assertIn("9000.00", body)
        self.assertIn("Rent", body)
        self.assertIn("8400.00", body)
        # 1000 -> 9000 is +800%
        self.assertIn("800.0%", body)

    def test_a_digest_row_is_recorded(self):
        self._august(user="alice")

        digest = MonthlyDigest.objects.get(user=self.alice)
        self.assertEqual(digest.month, date(2026, 8, 1))
        self.assertEqual(digest.total, Decimal("9000"))
        self.assertEqual(digest.expense_count, 2)

    # ---- Idempotency ---------------------------------------------------

    def test_running_twice_sends_only_once(self):
        # The scenario that motivates the whole design: cron fires again
        # after a worker restart.
        mail.outbox = []

        self._august()
        self._august()

        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(MonthlyDigest.objects.count(), 2)

    def test_second_run_reports_the_skips(self):
        self._august()

        output = self._august()

        self.assertIn("2 already sent", output)

    def test_the_row_is_claimed_before_the_email_is_sent(self):
        # If the email were sent first, a crash in between would re-send on
        # the next run. Claiming the row first makes the failure mode
        # "possibly not sent" rather than "possibly sent twice".
        order = []

        real_create = MonthlyDigest.objects.create

        def tracking_create(**kwargs):
            order.append("row")
            return real_create(**kwargs)

        with patch.object(MonthlyDigest.objects, "create", side_effect=tracking_create):
            with patch(
                "expenses.management.commands.send_monthly_digests.send_mail",
                side_effect=lambda *a, **k: order.append("email"),
            ):
                self._august(user="alice")

        self.assertEqual(order, ["row", "email"])

    def test_a_send_failure_does_not_resend_that_month(self):
        # The deliberate trade: at-most-once. For a digest, silence beats
        # a duplicate.
        with patch(
            "expenses.management.commands.send_monthly_digests.send_mail",
            side_effect=OSError("smtp down"),
        ):
            output = self._august(user="alice")

        self.assertIn("1 failed", output)
        self.assertTrue(MonthlyDigest.objects.filter(user=self.alice).exists())

        mail.outbox = []
        self._august(user="alice")
        self.assertEqual(len(mail.outbox), 0)

    def test_one_bad_address_does_not_stop_the_run(self):
        # The fan-out argument in miniature: user 40 failing must not cost
        # users 41-100 their email.
        def fail_for_alice(*args, **kwargs):
            if "alice@example.com" in kwargs.get("recipient_list", []):
                raise OSError("bad address")

        with patch(
            "expenses.management.commands.send_monthly_digests.send_mail",
            side_effect=fail_for_alice,
        ):
            output = self._august()

        self.assertIn("1 sent", output)
        self.assertIn("1 failed", output)

    # ---- Selection rules -----------------------------------------------

    def test_users_with_no_spending_are_skipped(self):
        carol = User.objects.create_user("carol", email="carol@example.com", password="pw12345!")
        mail.outbox = []

        output = self._august()

        self.assertNotIn(carol.email, [m.to[0] for m in mail.outbox])
        self.assertIn("1 with no spending", output)

    def test_an_empty_month_is_not_recorded_so_it_can_be_sent_later(self):
        # Recording a skip would block the digest if the user backfills.
        User.objects.create_user("carol", email="carol@example.com", password="pw12345!")

        self._august()

        self.assertFalse(MonthlyDigest.objects.filter(user__username="carol").exists())

    def test_inactive_users_are_skipped(self):
        self.bob.is_active = False
        self.bob.save(update_fields=["is_active"])
        mail.outbox = []

        self._august()

        self.assertEqual([m.to[0] for m in mail.outbox], ["alice@example.com"])

    def test_each_user_only_sees_their_own_numbers(self):
        mail.outbox = []

        self._august()

        by_address = {m.to[0]: m.body for m in mail.outbox}
        self.assertIn("9000.00", by_address["alice@example.com"])
        self.assertNotIn("9000.00", by_address["bob@example.com"])
        self.assertIn("250.00", by_address["bob@example.com"])

    # ---- Options -------------------------------------------------------

    def test_dry_run_sends_nothing_and_records_nothing(self):
        mail.outbox = []

        output = self._august(dry_run=True)

        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(MonthlyDigest.objects.count(), 0)
        self.assertIn("dry run", output)

    def test_month_defaults_to_the_previous_calendar_month(self):
        with patch("expenses.management.commands.send_monthly_digests.date") as mock_date:
            mock_date.today.return_value = date(2026, 9, 15)
            mock_date.side_effect = date
            mail.outbox = []

            self._run()

        # Run in September, it sends August.
        self.assertEqual(MonthlyDigest.objects.first().month, date(2026, 8, 1))

    def test_malformed_month_is_rejected(self):
        with self.assertRaises(CommandError):
            self._run(month="August")

    def test_january_rolls_back_to_the_previous_december(self):
        Expense.objects.create(
            user=self.alice,
            category=self.food,
            amount=Decimal("500"),
            spent_on=date(2025, 12, 10),
        )

        self._run(month="2025-12")

        self.assertEqual(MonthlyDigest.objects.get(user=self.alice).month, date(2025, 12, 1))


class DigestCursorTests(TransactionTestCase):
    """Runs the command against real commits.

    TestCase wraps each test in a transaction and rolls it back, so
    transaction.atomic() inside the command becomes a savepoint and never
    actually commits. That hid a real bug: the command iterated users with
    queryset.iterator(), which holds a server-side cursor open, and the
    first real commit invalidated it — the second user raised
    "cursor needed to be reset because of commit/rollback".

    Sixteen TestCase tests passed throughout. Only running the command for
    real surfaced it. TransactionTestCase is slower because it truncates
    tables between tests instead of rolling back, which is exactly why it
    is reserved for cases like this one.
    """

    def setUp(self):
        for name in ("alice", "bob", "carol"):
            user = User.objects.create_user(name, email=f"{name}@example.com", password="pw12345!")
            category = Category.objects.create(user=user, name="Food")
            Expense.objects.create(
                user=user,
                category=category,
                amount=Decimal("500"),
                spent_on=date(2026, 8, 5),
            )

    def test_multiple_users_survive_the_commit_inside_the_loop(self):
        out = StringIO()

        call_command("send_monthly_digests", month="2026-08", stdout=out, stderr=StringIO())

        # Before the fix this raised InterfaceError on the second user.
        self.assertIn("3 sent", out.getvalue())
        self.assertEqual(MonthlyDigest.objects.count(), 3)

    def test_idempotency_holds_across_real_commits(self):
        mail.outbox = []

        call_command("send_monthly_digests", month="2026-08", stdout=StringIO())
        call_command("send_monthly_digests", month="2026-08", stdout=StringIO())

        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(MonthlyDigest.objects.count(), 3)
