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
from django.urls import reverse

from expenses.extraction.errors import ExtractionError
from expenses.extraction.prefill import initial_from_scan
from expenses.models import BillScan, Category, Expense
from expenses.tasks import scan_bill
from expenses.tests.helpers import item_formset

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


class BillScanUploadViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )

    def setUp(self):
        self.client.force_login(self.alice)

    def test_upload_rejects_a_pdf_and_an_oversized_file(self):
        pdf = SimpleUploadedFile("bill.pdf", b"%PDF-1.4", content_type="application/pdf")
        response = self.client.post(reverse("expenses:bill_upload"), {"image": pdf})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "JPEG, PNG or WebP")
        self.assertFalse(BillScan.objects.exists())

        oversized = SimpleUploadedFile(
            "big.jpg", b"x" * (5 * 1024 * 1024 + 1), content_type="image/jpeg"
        )
        response = self.client.post(reverse("expenses:bill_upload"), {"image": oversized})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "too large")
        self.assertFalse(BillScan.objects.exists())

    def test_upload_queues_the_task_on_commit(self):
        image = SimpleUploadedFile("bill.jpg", b"fake-bytes", content_type="image/jpeg")

        with (
            patch("expenses.views.scan_bill.delay") as mock_delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.post(reverse("expenses:bill_upload"), {"image": image})

        self.assertRedirects(response, reverse("expenses:bill_list"))
        scan = BillScan.objects.get()
        mock_delay.assert_called_once_with(scan.pk)


class BillScanReviewViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")
        cls.food = Category.objects.create(user=cls.alice, name="Food")

    def setUp(self):
        self.client.force_login(self.alice)

    def _done_scan(self, user, **result_overrides):
        result = {
            "merchant": "Test Cafe",
            "bill_date": "2026-09-10",
            "total": "450.00",
            "lines": [],
            "tax": "0",
            "category_hint": "food",
            "confidence": 0.9,
            "provider": "fake",
        }
        result.update(result_overrides)
        return _make_scan(user, status=BillScan.Status.DONE, provider="fake", result=result)

    def test_review_of_someone_elses_scan_is_404(self):
        scan = self._done_scan(self.bob)

        response = self.client.get(reverse("expenses:bill_review", args=[scan.pk]))

        self.assertEqual(response.status_code, 404)

    def test_review_of_an_already_linked_scan_is_404(self):
        # A scan that already made an expense is not up for review again --
        # reopening the URL (a double-click, the back button, a second tab)
        # must not be able to create a second expense from the same bill.
        expense = Expense.objects.create(
            user=self.alice,
            category=self.food,
            amount=Decimal("450.00"),
            spent_on=date(2026, 9, 10),
            note="Test Cafe",
        )
        scan = self._done_scan(self.alice)
        scan.expense = expense
        scan.save(update_fields=["expense"])

        response = self.client.get(reverse("expenses:bill_review", args=[scan.pk]))

        self.assertEqual(response.status_code, 404)

    def test_two_scanned_lines_both_render(self):
        # Locks in the fix for a real bug: initial= alone does not grow an
        # unbound model formset's form count past the factory's extra=1, so
        # a second scanned line silently failed to appear until this view
        # raised formset.extra to fit every line.
        scan = self._done_scan(
            self.alice,
            lines=[
                {"name": "Coffee", "amount": "150.00"},
                {"name": "Sandwich", "amount": "250.00"},
            ],
        )

        response = self.client.get(reverse("expenses:bill_review", args=[scan.pk]))

        formset = response.context["formset"]
        self.assertEqual(len(formset.forms), 2)
        self.assertEqual(formset.forms[0].initial["name"], "Coffee")
        self.assertEqual(formset.forms[1].initial["name"], "Sandwich")
        self.assertContains(response, "Coffee")
        self.assertContains(response, "Sandwich")

    def test_review_prefills_amount_note_and_matching_category(self):
        scan = self._done_scan(self.alice)

        response = self.client.get(reverse("expenses:bill_review", args=[scan.pk]))

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form.initial["note"], "Test Cafe")
        self.assertEqual(form.initial["amount"], Decimal("450.00"))
        self.assertEqual(form.initial["category"], self.food)

    def test_prefill_matches_category_case_insensitively(self):
        scan = self._done_scan(self.alice, category_hint="FOOD")

        initial, _line_initials = initial_from_scan(scan, self.alice)

        self.assertEqual(initial["category"], self.food)

    def test_saving_the_review_links_the_expense(self):
        scan = self._done_scan(self.alice)

        response = self.client.post(
            reverse("expenses:bill_review", args=[scan.pk]),
            {
                "category": self.food.pk,
                "amount": "450.00",
                "spent_on": "2026-09-10",
                "note": "Test Cafe",
                **item_formset(),
            },
        )

        self.assertRedirects(response, reverse("expenses:expense_list"))
        scan.refresh_from_db()
        self.assertIsNotNone(scan.expense)
        self.assertEqual(scan.expense.note, "Test Cafe")
        self.assertEqual(scan.expense.user, self.alice)

    def test_invalid_line_item_does_not_link_the_scan_or_claim_success(self):
        # The parent form can be valid while the formset is not (here: a
        # line item with an amount but no name). ItemFormSetMixin.form_valid
        # short-circuits before saving in that case, so self.object stays
        # None -- nothing was created, and the scan must not be linked or
        # reported as saved.
        scan = self._done_scan(self.alice)

        response = self.client.post(
            reverse("expenses:bill_review", args=[scan.pk]),
            {
                "category": self.food.pk,
                "amount": "450.00",
                "spent_on": "2026-09-10",
                "note": "Test Cafe",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-name": "",
                "items-0-amount": "10.00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Expense.objects.exists())
        scan.refresh_from_db()
        self.assertIsNone(scan.expense)
        self.assertNotContains(response, "Expense added from your scanned bill.")
