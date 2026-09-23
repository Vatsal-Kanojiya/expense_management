"""BillScan: the record of a bill photo and what a vision model read from it.

Mirrors ExportJob's shape (see test_exports.py) -- a row for progress and
status, updated only by the task. The model tests are here; the task tests
join in S2 (this batch), and the view tests join in S3.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from expenses.extraction.errors import ExtractionError
from expenses.models import BillScan, Category, Expense
from expenses.tasks import scan_bill

User = get_user_model()


def _make_scan(user, **kwargs):
    image = kwargs.pop("image", None) or SimpleUploadedFile(
        "bill.jpg", b"fake-image-bytes", content_type="image/jpeg"
    )
    return BillScan.objects.create(user=user, image=image, **kwargs)


class BillScanModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )

    def _make_scan(self, **kwargs):
        return _make_scan(self.alice, **kwargs)

    def test_new_scan_is_pending(self):
        scan = self._make_scan()

        self.assertEqual(scan.status, BillScan.Status.PENDING)

    def test_upload_path_is_unguessable_and_keeps_extension(self):
        scan = self._make_scan()

        # The path must not be a predictable function of the filename or the
        # scan's pk -- same reasoning as export_upload_path.
        self.assertTrue(scan.image.name.startswith(f"bills/{self.alice.pk}/"))
        self.assertTrue(scan.image.name.endswith(".jpg"))
        self.assertNotIn("bill.jpg", scan.image.name)

    def test_deleting_the_expense_keeps_the_scan(self):
        category = Category.objects.create(user=self.alice, name="Food")
        expense = Expense.objects.create(
            user=self.alice,
            category=category,
            amount=Decimal("100.00"),
            spent_on=date(2026, 9, 1),
            note="Lunch",
        )
        scan = self._make_scan(status=BillScan.Status.DONE, expense=expense)

        expense.delete()
        scan.refresh_from_db()

        self.assertIsNone(scan.expense)
        self.assertEqual(scan.status, BillScan.Status.DONE)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class BillScanTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )

    def test_task_stores_the_fake_result_as_json_strings(self):
        scan = _make_scan(self.alice)

        scan_bill(scan.pk)
        scan.refresh_from_db()

        self.assertEqual(scan.status, BillScan.Status.DONE)
        self.assertEqual(scan.provider, "fake")
        self.assertIsNotNone(scan.completed_at)
        # Amounts are strings, not Decimal -- a JSONField cannot round-trip
        # Decimal, and a float would silently round paise.
        self.assertEqual(scan.result["total"], "450.00")
        self.assertEqual(scan.result["tax"], "50.00")
        self.assertEqual(
            scan.result["lines"],
            [
                {"name": "Coffee", "amount": "150.00"},
                {"name": "Sandwich", "amount": "250.00"},
            ],
        )
        self.assertEqual(scan.result["merchant"], "Test Cafe")
        self.assertEqual(scan.result["category_hint"], "food")

    def test_task_is_idempotent_when_already_done(self):
        scan = _make_scan(self.alice, status=BillScan.Status.DONE, provider="fake")

        with patch("expenses.tasks.extract_bill") as mock_extract:
            scan_bill(scan.pk)

        mock_extract.assert_not_called()

    def test_extraction_error_fails_without_retry(self):
        scan = _make_scan(self.alice)

        with patch("expenses.tasks.extract_bill", side_effect=ExtractionError("blurry photo")):
            # Must not raise -- a bill the model cannot read is not a
            # transient failure, so scan_bill swallows it rather than
            # letting Celery retry the same unreadable image.
            scan_bill(scan.pk)

        scan.refresh_from_db()
        self.assertEqual(scan.status, BillScan.Status.FAILED)
        self.assertIn("blurry photo", scan.error)
