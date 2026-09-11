"""Phase 16: the four security gaps that stayed open longest."""

from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.deletion import delete_account
from expenses.models import (
    Category,
    Expense,
    ExpenseItem,
    ExportJob,
    ItemShare,
    Participant,
    Settlement,
)

User = get_user_model()

with_cache = override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "hardening-tests",
        }
    }
)


@with_cache
class LoginThrottleTests(TestCase):
    """Known issue 15, login half."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="correct-horse-battery"
        )

    def setUp(self):
        cache.clear()

    def _attempt(self, password="wrong"):
        return self.client.post(
            reverse("accounts:login"), {"username": "alice", "password": password}
        )

    def test_repeated_failures_are_eventually_refused(self):
        for _ in range(10):
            self._attempt()

        response = self._attempt()

        # 429, not a 200 that looks like an ordinary failure. A throttled
        # response indistinguishable from a wrong password is invisible to
        # monitoring and to any client that would otherwise back off.
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Too many sign-in attempts", status_code=429)

    def test_a_correct_password_still_works_below_the_limit(self):
        for _ in range(3):
            self._attempt()

        response = self._attempt(password="correct-horse-battery")

        self.assertEqual(response.status_code, 302)

    def test_success_clears_the_counter(self):
        # Otherwise ten legitimate sign-ins in a window lock out exactly
        # the wrong person.
        for _ in range(9):
            self._attempt()
        self._attempt(password="correct-horse-battery")
        self.client.logout()

        for _ in range(9):
            self._attempt()

        self.assertEqual(self._attempt(password="correct-horse-battery").status_code, 302)

    def test_throttling_one_account_does_not_lock_another(self):
        for _ in range(11):
            self._attempt()

        User.objects.create_user("bob", email="bob@example.com", password="another-password")
        response = self.client.post(
            reverse("accounts:login"), {"username": "bob", "password": "another-password"}
        )

        # Keyed on (address, username). Keyed on address alone, one office
        # behind one NAT would lock out everybody.
        self.assertEqual(response.status_code, 302)


@with_cache
class PasswordResetThrottleTests(TestCase):
    """Known issue 15, reset half."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )

    def setUp(self):
        cache.clear()
        mail.outbox.clear()

    def _request(self):
        return self.client.post(reverse("accounts:password_reset"), {"email": "alice@example.com"})

    def test_reset_mail_is_capped(self):
        for _ in range(5):
            self._request()

        self._request()

        # Five sent, the sixth refused. Every accepted request lands in an
        # inbox the requester may not own, so the limit protects a third
        # party rather than this application.
        self.assertEqual(len(mail.outbox), 5)

    def test_the_first_few_still_send(self):
        self._request()

        self.assertEqual(len(mail.outbox), 1)


class AccountDeletionTests(TestCase):
    """Known issue 10, open since session 4."""

    def setUp(self):
        self.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        self.category = Category.objects.create(user=self.alice, name="Food")
        self.rahul = Participant.objects.create(user=self.alice, name="Rahul")
        self.expense = Expense.objects.create(
            user=self.alice,
            category=self.category,
            amount=Decimal("900.00"),
            spent_on=date.today(),
        )
        self.expense.participants.add(self.rahul)
        item = ExpenseItem.objects.create(
            expense=self.expense, name="Pizza", amount=Decimal("900.00")
        )
        ItemShare.objects.create(item=item, participant=self.rahul)
        Settlement.objects.create(user=self.alice, participant=self.rahul, amount=Decimal("100.00"))

    def test_the_plain_delete_still_raises(self):
        """Documents why the ordered version exists.

        Expense.category is PROTECT, and Django's collector honours that
        even though the protecting expense is in the same delete plan.
        """
        from django.db.models import ProtectedError

        with self.assertRaises(ProtectedError):
            self.alice.delete()

    def test_the_ordered_delete_succeeds(self):
        delete_account(self.alice)

        self.assertEqual(User.objects.filter(username="alice").count(), 0)

    def test_nothing_of_theirs_survives(self):
        delete_account(self.alice)

        self.assertEqual(Expense.objects.count(), 0)
        self.assertEqual(ExpenseItem.objects.count(), 0)
        self.assertEqual(ItemShare.objects.count(), 0)
        self.assertEqual(Category.objects.count(), 0)
        self.assertEqual(Participant.objects.count(), 0)
        self.assertEqual(Settlement.objects.count(), 0)

    def test_another_users_data_is_untouched(self):
        bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")
        bob_category = Category.objects.create(user=bob, name="Food")
        Expense.objects.create(
            user=bob, category=bob_category, amount=Decimal("10.00"), spent_on=date.today()
        )

        delete_account(self.alice)

        self.assertEqual(Expense.objects.count(), 1)
        self.assertEqual(Category.objects.count(), 1)

    def test_the_view_requires_the_username_typed_exactly(self):
        self.client.force_login(self.alice)

        response = self.client.post(reverse("accounts:delete_account"), {"confirm": "wrong"})

        self.assertEqual(response.status_code, 400)
        self.assertTrue(User.objects.filter(username="alice").exists())

    def test_the_view_deletes_on_confirmation(self):
        self.client.force_login(self.alice)

        self.client.post(reverse("accounts:delete_account"), {"confirm": "alice"})

        self.assertFalse(User.objects.filter(username="alice").exists())

    def test_anonymous_users_cannot_reach_it(self):
        response = self.client.get(reverse("accounts:delete_account"))

        self.assertEqual(response.status_code, 302)


class ExportRetentionTests(TestCase):
    """Known issue 19."""

    def setUp(self):
        self.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )

    def _job(self, age_days):
        job = ExportJob.objects.create(
            user=self.alice, start=date(2026, 1, 1), end=date(2026, 1, 31)
        )
        # auto_now_add cannot be set on create, so the row is corrected
        # afterwards with a queryset update.
        ExportJob.objects.filter(pk=job.pk).update(
            requested_at=timezone.now() - timedelta(days=age_days)
        )
        return job

    def test_old_jobs_are_removed(self):
        self._job(age_days=30)

        call_command("purge_exports", stdout=StringIO())

        self.assertEqual(ExportJob.objects.count(), 0)

    def test_recent_jobs_survive(self):
        self._job(age_days=1)

        call_command("purge_exports", stdout=StringIO())

        self.assertEqual(ExportJob.objects.count(), 1)

    def test_the_retention_period_is_configurable(self):
        self._job(age_days=10)

        call_command("purge_exports", days=30, stdout=StringIO())

        self.assertEqual(ExportJob.objects.count(), 1)

    def test_a_dry_run_removes_nothing(self):
        self._job(age_days=30)
        out = StringIO()

        call_command("purge_exports", dry_run=True, stdout=out)

        self.assertEqual(ExportJob.objects.count(), 1)
        self.assertIn("would remove", out.getvalue())

    def test_running_twice_is_harmless(self):
        # Beat can fire a task more than once. A file already gone stays
        # gone, so this needs no idempotency guard of its own.
        self._job(age_days=30)

        call_command("purge_exports", stdout=StringIO())
        call_command("purge_exports", stdout=StringIO())

        self.assertEqual(ExportJob.objects.count(), 0)
