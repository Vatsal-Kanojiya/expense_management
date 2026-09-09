"""CSV export: the request-triggered case that justifies a task queue.

Tasks run eagerly here, so no broker is needed. That is a deliberate
partial lie — eager mode runs the task inline and in the same
transaction, so it cannot catch the on_commit race or a genuine
redelivery. Those are covered by asserting dispatch happens on commit,
and by calling the task twice to simulate redelivery.
"""

import csv
import io
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from expenses.models import Category, Expense, ExportJob
from expenses.tasks import build_expense_export

User = get_user_model()


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class ExportViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")
        cls.category = Category.objects.create(user=cls.alice, name="Food")
        Expense.objects.create(
            user=cls.alice,
            category=cls.category,
            amount=Decimal("10.00"),
            spent_on=date(2026, 9, 5),
            note="Milk",
        )

    def setUp(self):
        self.client.force_login(self.alice)

    def test_export_requires_login(self):
        self.client.logout()

        response = self.client.post(reverse("expenses:export_create"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_requesting_an_export_returns_immediately(self):
        response = self.client.post(
            reverse("expenses:export_create"), {"start": "2026-09-01", "end": "2026-09-30"}
        )

        # The whole point: a redirect, not a file. The user is not held on
        # the connection while the CSV is built.
        self.assertRedirects(response, reverse("expenses:export_list"))
        self.assertEqual(ExportJob.objects.count(), 1)

    def test_job_is_owned_by_the_requesting_user(self):
        self.client.post(reverse("expenses:export_create"), {"start": "2026-09-01"})

        self.assertEqual(ExportJob.objects.get().user, self.alice)

    def test_dispatch_waits_for_the_transaction_to_commit(self):
        # Dispatching inside an open transaction is a real race: the worker
        # can query for a row the web process has not committed. Asserting
        # on_commit is used is the only way to catch that in a test, since
        # TestCase never actually commits.
        with patch("expenses.views.transaction.on_commit") as on_commit:
            self.client.post(reverse("expenses:export_create"), {"start": "2026-09-01"})

        on_commit.assert_called_once()

    def test_export_list_shows_only_your_own_jobs(self):
        mine = ExportJob.objects.create(
            user=self.alice, start=date(2026, 9, 1), end=date(2026, 9, 30)
        )
        theirs = ExportJob.objects.create(
            user=self.bob, start=date(2026, 9, 1), end=date(2026, 9, 30)
        )

        response = self.client.get(reverse("expenses:export_list"))

        self.assertIn(mine, response.context["jobs"])
        self.assertNotIn(theirs, response.context["jobs"])

    def test_cannot_download_another_users_export(self):
        theirs = ExportJob.objects.create(
            user=self.bob, start=date(2026, 9, 1), end=date(2026, 9, 30)
        )
        build_expense_export(theirs.pk)

        response = self.client.get(reverse("expenses:export_download", args=[theirs.pk]))

        self.assertEqual(response.status_code, 404)

    def test_downloading_an_unfinished_export_is_404_not_a_broken_file(self):
        job = ExportJob.objects.create(
            user=self.alice, start=date(2026, 9, 1), end=date(2026, 9, 30)
        )

        response = self.client.get(reverse("expenses:export_download", args=[job.pk]))

        self.assertEqual(response.status_code, 404)

    def test_completed_export_downloads_as_an_attachment(self):
        job = ExportJob.objects.create(
            user=self.alice, start=date(2026, 9, 1), end=date(2026, 9, 30)
        )
        build_expense_export(job.pk)

        response = self.client.get(reverse("expenses:export_download", args=[job.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class ExportTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")
        cls.food = Category.objects.create(user=cls.alice, name="Food")
        cls.rent = Category.objects.create(user=cls.alice, name="Rent")
        bob_cat = Category.objects.create(user=cls.bob, name="BobOnly")

        Expense.objects.create(
            user=cls.alice,
            category=cls.food,
            amount=Decimal("10.50"),
            spent_on=date(2026, 9, 5),
            note="Milk",
        )
        Expense.objects.create(
            user=cls.alice,
            category=cls.rent,
            amount=Decimal("8400.00"),
            spent_on=date(2026, 9, 1),
            note="",
        )
        # Outside the range, and someone else's — neither may appear.
        Expense.objects.create(
            user=cls.alice,
            category=cls.food,
            amount=Decimal("99.00"),
            spent_on=date(2026, 8, 1),
            note="August",
        )
        Expense.objects.create(
            user=cls.bob,
            category=bob_cat,
            amount=Decimal("55555.00"),
            spent_on=date(2026, 9, 9),
            note="Bob secret",
        )

    def _run(self):
        job = ExportJob.objects.create(
            user=self.alice, start=date(2026, 9, 1), end=date(2026, 9, 30)
        )
        build_expense_export(job.pk, site_url="http://testserver")
        job.refresh_from_db()
        return job

    def _rows(self, job):
        return list(csv.reader(io.StringIO(job.file.read().decode())))

    def test_job_reaches_complete(self):
        job = self._run()

        self.assertEqual(job.status, ExportJob.Status.COMPLETE)
        self.assertEqual(job.row_count, 2)
        self.assertIsNotNone(job.completed_at)

    def test_csv_has_a_header_and_the_right_rows(self):
        rows = self._rows(self._run())

        self.assertEqual(rows[0], ["Date", "Category", "Amount", "Note"])
        self.assertEqual(rows[1], ["2026-09-01", "Rent", "8400.00", ""])
        self.assertEqual(rows[2], ["2026-09-05", "Food", "10.50", "Milk"])

    def test_export_excludes_other_users_and_other_dates(self):
        body = self._run().file.read().decode()

        self.assertNotIn("Bob secret", body)
        self.assertNotIn("55555", body)
        self.assertNotIn("August", body)

    def test_an_email_with_a_link_is_sent(self):
        mail.outbox = []
        job = self._run()

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("alice@example.com", mail.outbox[0].to)
        # A link, not an attachment: attachments hit size limits and leave a
        # copy of the user's financial history in an inbox forever.
        self.assertEqual(len(mail.outbox[0].attachments), 0)
        self.assertIn(reverse("expenses:export_download", args=[job.pk]), mail.outbox[0].body)

    def test_redelivery_does_not_redo_the_work_or_resend(self):
        # acks_late means a task CAN run twice. That is the trade for not
        # losing work, and it is why the completed check exists.
        job = self._run()
        original_name = job.file.name
        mail.outbox = []

        build_expense_export(job.pk, site_url="http://testserver")

        job.refresh_from_db()
        self.assertEqual(job.file.name, original_name)
        self.assertEqual(len(mail.outbox), 0)

    def test_failure_is_recorded_rather_than_leaving_the_job_running(self):
        job = ExportJob.objects.create(
            user=self.alice, start=date(2026, 9, 1), end=date(2026, 9, 30)
        )

        with patch("expenses.tasks._write_csv", side_effect=ValueError("disk full")):
            with self.assertRaises(ValueError):
                build_expense_export(job.pk)

        job.refresh_from_db()
        # A job stuck on "running" forever tells the user nothing.
        self.assertEqual(job.status, ExportJob.Status.FAILED)
        self.assertIn("disk full", job.error)

    def test_empty_range_still_produces_a_valid_file(self):
        job = ExportJob.objects.create(
            user=self.alice, start=date(2020, 1, 1), end=date(2020, 1, 31)
        )
        build_expense_export(job.pk)
        job.refresh_from_db()

        rows = self._rows(job)
        self.assertEqual(job.status, ExportJob.Status.COMPLETE)
        self.assertEqual(job.row_count, 0)
        self.assertEqual(rows, [["Date", "Category", "Amount", "Note"]])

    def test_file_path_is_not_guessable(self):
        job = self._run()

        # Defence in depth. The view checks ownership, but if the file is
        # ever served directly by nginx or synced to a bucket, the path
        # must not be enumerable from the job id.
        #
        # Asserting the pk is absent from the name would be a bad test: a
        # 32-character hex string contains almost any single digit by
        # chance. Assert the real property instead — the name IS a uuid4.
        filename = job.file.name.rsplit("/", 1)[-1]

        self.assertRegex(filename, r"^[0-9a-f]{32}\.csv$")
        self.assertTrue(job.file.name.startswith(f"exports/{self.alice.pk}/"))
