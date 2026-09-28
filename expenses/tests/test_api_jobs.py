"""Exports and bill scans through the API (phase 20.6)."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from expenses.models import BillScan, Category, Expense, ExportJob

User = get_user_model()
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def url(name, *args):
    return reverse(f"api:v1:{name}", args=args)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class JobTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", "pw-Alice-123")
        cls.bob = User.objects.create_user("bob", "bob@example.com", "pw-Bob-12345")
        cls.food = Category.objects.create(user=cls.alice, name="Food")
        Expense.objects.create(
            user=cls.alice,
            category=cls.food,
            amount=Decimal("120"),
            spent_on=date(2026, 3, 3),
            note="Lunch",
        )

    def setUp(self):
        self.client.force_login(self.alice)


class ExportTests(JobTestCase):
    def request_export(self, **dates):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(url("export-list"), dates, content_type="application/json")

    def test_request_poll_download(self):
        response = self.request_export(start="2026-03-01", end="2026-03-31")

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "pending")  # as answered, before the worker
        job = self.client.get(url("export-detail", response.json()["id"])).json()
        self.assertEqual((job["status"], job["row_count"]), ("complete", 1))

        download = self.client.get(job["download_url"])
        self.assertEqual(download.status_code, 200)
        self.assertIn("expenses-20260301-20260331.csv", download["Content-Disposition"])
        self.assertIn(b"Lunch", b"".join(download.streaming_content))

    @override_settings(FRONTEND_URL="")  # the default, whatever the environment says
    def test_the_email_links_to_the_django_page_by_default(self):
        job_id = self.request_export().json()["id"]

        self.assertIn(reverse("expenses:export_download", args=[job_id]), mail.outbox[0].body)

    @override_settings(FRONTEND_URL="https://app.example.com")
    def test_with_a_frontend_the_email_links_there(self):
        job_id = self.request_export().json()["id"]

        self.assertIn(f"https://app.example.com/exports/{job_id}", mail.outbox[0].body)

    def test_an_unfinished_export_is_a_409(self):
        job = ExportJob.objects.create(
            user=self.alice, start=date(2026, 1, 1), end=date(2026, 1, 31)
        )

        response = self.client.get(url("export-download", job.pk))

        self.assertEqual((response.status_code, response.json()["code"]), (409, "not_ready"))
        self.assertIsNone(self.client.get(url("export-detail", job.pk)).json()["download_url"])

    def test_someone_elses_export_is_a_404(self):
        theirs = ExportJob.objects.create(
            user=self.bob, start=date(2026, 1, 1), end=date(2026, 1, 31)
        )

        self.assertEqual(self.client.get(url("export-download", theirs.pk)).status_code, 404)
        self.assertEqual(self.client.get(url("export-list")).json()["results"], [])


class BillScanTests(JobTestCase):
    def upload(self, content=PNG, name="bill.png", content_type="image/png"):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                url("bill-scan-list"), {"image": SimpleUploadedFile(name, content, content_type)}
            )

    def test_upload_scan_prefill_save(self):
        uploaded = self.upload()
        self.assertEqual(uploaded.status_code, 202)
        scan_id = uploaded.json()["id"]

        scan = self.client.get(url("bill-scan-detail", scan_id)).json()
        self.assertEqual(
            (scan["status"], scan["provider"], scan["expense"]), ("done", "fake", None)
        )
        self.assertEqual(self.client.get(scan["image_url"]).status_code, 200)

        draft = self.client.get(url("bill-scan-prefill", scan_id)).json()
        self.assertEqual(
            (draft["note"], draft["amount"], draft["category"], draft["misc_amount"]),
            ("Test Cafe", "450.00", self.food.pk, "50.00"),
        )
        self.assertEqual([line["name"] for line in draft["items"]], ["Coffee", "Sandwich"])

        saved = self.client.post(url("expense-list"), draft, content_type="application/json")
        self.assertEqual(saved.status_code, 201, saved.content)
        self.assertEqual(BillScan.objects.get(pk=scan_id).expense_id, saved.json()["id"])
        self.assertTrue(saved.json()["is_balanced"])

    def test_a_scan_becomes_an_expense_at_most_once(self):
        scan_id = self.upload().json()["id"]
        draft = self.client.get(url("bill-scan-prefill", scan_id)).json()
        self.client.post(url("expense-list"), draft, content_type="application/json")

        again = self.client.post(url("expense-list"), draft, content_type="application/json")
        prefill = self.client.get(url("bill-scan-prefill", scan_id))

        self.assertEqual(again.status_code, 400)
        self.assertIn("bill_scan", again.json())
        self.assertEqual((prefill.status_code, prefill.json()["code"]), (409, "already_saved"))
        self.assertEqual(Expense.objects.filter(note="Test Cafe").count(), 1)

    def test_an_unfinished_scan_has_no_draft_and_cannot_be_saved(self):
        scan = BillScan.objects.create(user=self.alice, image=SimpleUploadedFile("b.png", PNG))

        prefill = self.client.get(url("bill-scan-prefill", scan.pk))
        saved = self.client.post(
            url("expense-list"),
            {
                "category": self.food.pk,
                "amount": "10",
                "spent_on": "2026-03-01",
                "note": "x",
                "bill_scan": scan.pk,
            },
            content_type="application/json",
        )

        self.assertEqual((prefill.status_code, prefill.json()["code"]), (409, "not_ready"))
        self.assertEqual(saved.status_code, 400)

    def test_only_photos_are_accepted(self):
        response = self.upload(b"%PDF-1.4", "bill.pdf", "application/pdf")

        self.assertEqual(response.status_code, 400)
        self.assertIn("image", response.json())

    def test_someone_elses_scan_is_invisible_and_unusable(self):
        theirs = BillScan.objects.create(
            user=self.bob, image=SimpleUploadedFile("b.png", PNG), status=BillScan.Status.DONE
        )

        self.assertEqual(self.client.get(url("bill-scan-image", theirs.pk)).status_code, 404)
        saved = self.client.post(
            url("expense-list"),
            {
                "category": self.food.pk,
                "amount": "10",
                "spent_on": "2026-03-01",
                "note": "x",
                "bill_scan": theirs.pk,
            },
            content_type="application/json",
        )
        self.assertEqual(saved.status_code, 400)
