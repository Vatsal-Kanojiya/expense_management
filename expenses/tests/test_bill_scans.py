"""BillScan: the record of a bill photo and what a vision model read from it.

Mirrors ExportJob's shape (see test_exports.py) -- a row for progress and
status, updated only by the task. The model-only tests live here; the task
and view tests join this file in S2 and S3.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from expenses.models import BillScan, Category, Expense

User = get_user_model()


class BillScanModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )

    def _make_scan(self, **kwargs):
        from django.core.files.uploadedfile import SimpleUploadedFile

        image = kwargs.pop("image", None) or SimpleUploadedFile(
            "bill.jpg", b"fake-image-bytes", content_type="image/jpeg"
        )
        return BillScan.objects.create(user=self.alice, image=image, **kwargs)

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
