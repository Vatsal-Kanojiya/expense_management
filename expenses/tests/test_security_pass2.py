"""Security pass 2 (docs/HANDOVER.md): files in and out of the app.

Four items, checked one by one, in the order HANDOVER.md lists them:
verifying a bill photo's real type, refusing an oversized upload early, a
per-account limit on creating scans and exports, and safe CSV cells.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts import ratelimit
from config.middleware import MaxUploadSizeMiddleware
from expenses.extraction import (
    ACCEPTED_MIME_TYPES,
    IMAGE_EXTENSIONS,
    MAX_UPLOAD_SIZE,
    sniff_image_type,
)
from expenses.models import BillScan, Category, Expense, ExportJob
from expenses.tasks import _csv_safe, _write_csv

User = get_user_model()
PASSWORD = "Str0ng-Enough-Pass"

# Real signatures -- what a decoder, or now BillScanForm, actually checks.
JPEG = b"\xff\xd8\xff" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32
NOT_AN_IMAGE = b"%PDF-1.4 this is not a photo at all"


# --- 1. Bill photos: the bytes are checked, not the declared type --------


class SniffImageTypeTests(SimpleTestCase):
    def test_recognises_jpeg_png_and_webp_by_their_signature(self):
        self.assertEqual(sniff_image_type(JPEG), "image/jpeg")
        self.assertEqual(sniff_image_type(PNG), "image/png")
        self.assertEqual(sniff_image_type(WEBP), "image/webp")

    def test_anything_else_is_none(self):
        self.assertIsNone(sniff_image_type(NOT_AN_IMAGE))
        self.assertIsNone(sniff_image_type(b""))
        # A PNG signature truncated before the WEBP check can even look at
        # byte 8 must not accidentally match anything.
        self.assertIsNone(sniff_image_type(b"RIFF\x00\x00\x00\x00"))

    def test_every_accepted_mime_type_has_a_extension_to_save_under(self):
        self.assertEqual(set(IMAGE_EXTENSIONS), ACCEPTED_MIME_TYPES)


class BillScanUploadContentSniffingTests(TestCase):
    """BillScanForm.clean_image, through the web page that owns it."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def setUp(self):
        self.client.force_login(self.alice)

    def upload(self, content, filename="bill.jpg", content_type="image/jpeg"):
        image = SimpleUploadedFile(filename, content, content_type=content_type)
        with patch("expenses.views.scan_bill.delay"), self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse("expenses:bill_upload"), {"image": image})

    def test_a_renamed_file_claiming_to_be_a_photo_is_rejected(self):
        # The old check trusted exactly this: a declared Content-Type of
        # image/jpeg on bytes that are not a JPEG at all.
        response = self.upload(NOT_AN_IMAGE, filename="bill.jpg", content_type="image/jpeg")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "JPEG, PNG or WebP")
        self.assertFalse(BillScan.objects.exists())

    def test_a_real_photo_is_accepted_even_with_a_misleading_name_and_type(self):
        # The declared type is wrong and the filename has no image
        # extension at all -- only the bytes say this is a JPEG.
        response = self.upload(JPEG, filename="notes.dat", content_type="application/octet-stream")

        self.assertRedirects(response, reverse("expenses:bill_list"))
        scan = BillScan.objects.get()
        # Saved under the extension the bytes verified as, not "notes.dat".
        self.assertTrue(scan.image.name.endswith(".jpg"))
        self.assertNotIn("notes", scan.image.name)

    def test_png_and_webp_are_each_saved_under_their_own_verified_extension(self):
        png_scan = self.upload(PNG, filename="a.jpg", content_type="image/jpeg")
        self.assertRedirects(png_scan, reverse("expenses:bill_list"))
        self.assertTrue(BillScan.objects.get().image.name.endswith(".png"))

        BillScan.objects.all().delete()

        webp_scan = self.upload(WEBP, filename="b.png", content_type="image/png")
        self.assertRedirects(webp_scan, reverse("expenses:bill_list"))
        self.assertTrue(BillScan.objects.get().image.name.endswith(".webp"))

    def test_the_5mb_rule_is_unchanged(self):
        oversized = JPEG + b"\x00" * MAX_UPLOAD_SIZE
        response = self.upload(oversized)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "too large")
        self.assertFalse(BillScan.objects.exists())


class BillScanImageServingTests(TestCase):
    """The scan image endpoint (expenses/api/jobs.py) serves what was verified."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        cls.bob = User.objects.create_user("bob", "bob@example.com", PASSWORD)

    def setUp(self):
        self.client.force_login(self.alice)

    def test_the_image_is_served_with_its_verified_type_and_nosniff(self):
        scan = BillScan.objects.create(
            user=self.alice, image=SimpleUploadedFile("bill.png", PNG, content_type="image/png")
        )

        response = self.client.get(reverse("api:v1:bill-scan-image", args=[scan.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_someone_elses_scan_image_is_still_a_404_with_nosniff_unaffected(self):
        theirs = BillScan.objects.create(
            user=self.bob, image=SimpleUploadedFile("bill.jpg", JPEG, content_type="image/jpeg")
        )

        response = self.client.get(reverse("api:v1:bill-scan-image", args=[theirs.pk]))

        self.assertEqual(response.status_code, 404)


# --- 2. Upload size: refused as early as Django allows --------------------


class UploadSizeSettingsTests(SimpleTestCase):
    def test_the_memory_limits_are_sized_from_max_upload_size_with_headroom(self):
        from django.conf import settings

        self.assertGreater(settings.DATA_UPLOAD_MAX_MEMORY_SIZE, MAX_UPLOAD_SIZE)
        self.assertEqual(settings.DATA_UPLOAD_MAX_MEMORY_SIZE, MAX_UPLOAD_SIZE + 1024 * 1024)
        self.assertEqual(settings.FILE_UPLOAD_MAX_MEMORY_SIZE, settings.DATA_UPLOAD_MAX_MEMORY_SIZE)


class MaxUploadSizeMiddlewareTests(SimpleTestCase):
    """The earliest check: Content-Length alone, before the view runs."""

    def _call(self, content_length):
        get_response = Mock(return_value=HttpResponse("ok"))
        middleware = MaxUploadSizeMiddleware(get_response)
        extra = {} if content_length is None else {"CONTENT_LENGTH": content_length}
        request = RequestFactory().post("/", **extra)

        return middleware(request), get_response

    def test_a_declared_size_within_the_limit_reaches_the_view(self):
        response, get_response = self._call("1000")

        self.assertEqual(response.status_code, 200)
        get_response.assert_called_once()

    def test_a_declared_size_over_the_limit_is_refused_without_calling_the_view(self):
        from django.conf import settings

        response, get_response = self._call(str(settings.DATA_UPLOAD_MAX_MEMORY_SIZE + 1))

        self.assertEqual(response.status_code, 413)
        get_response.assert_not_called()

    def test_no_content_length_passes_through(self):
        response, get_response = self._call(None)

        self.assertEqual(response.status_code, 200)
        get_response.assert_called_once()

    def test_a_malformed_content_length_fails_open_rather_than_crash(self):
        response, get_response = self._call("not-a-number")

        self.assertEqual(response.status_code, 200)
        get_response.assert_called_once()


class UploadSizeIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def setUp(self):
        self.client.force_login(self.alice)

    def test_a_request_declaring_an_oversized_body_never_reaches_the_form(self):
        image = SimpleUploadedFile("bill.jpg", JPEG, content_type="image/jpeg")

        response = self.client.post(
            reverse("expenses:bill_upload"),
            {"image": image},
            CONTENT_LENGTH=str(50 * 1024 * 1024),
        )

        self.assertEqual(response.status_code, 413)
        self.assertFalse(BillScan.objects.exists())


# --- 3. A per-account limit on scans and exports ---------------------------

with_cache = override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "security-pass2-tests",
        }
    }
)


@with_cache
class JobLimitTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        cls.bob = User.objects.create_user("bob", "bob@example.com", PASSWORD)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)


class ScanLimitTests(JobLimitTestCase):
    def upload_web(self, n):
        image = SimpleUploadedFile(f"bill{n}.jpg", JPEG, content_type="image/jpeg")
        with patch("expenses.views.scan_bill.delay"):
            return self.client.post(reverse("expenses:bill_upload"), {"image": image})

    def upload_api(self, n):
        image = SimpleUploadedFile(f"bill{n}.jpg", JPEG, content_type="image/jpeg")
        with patch("expenses.api.jobs.scan_bill.delay"):
            return self.client.post("/api/v1/bill-scans/", {"image": image})

    @patch.object(ratelimit, "SCAN_LIMIT", 2)
    def test_the_page_and_the_api_share_one_budget(self):
        self.assertEqual(self.upload_web(1).status_code, 302)
        self.assertEqual(self.upload_api(2).status_code, 202)

        self.assertEqual(self.upload_web(3).status_code, 429)
        response = self.upload_api(4)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["code"], "rate_limited")
        self.assertEqual(BillScan.objects.count(), 2)

    @patch.object(ratelimit, "SCAN_LIMIT", 1)
    def test_a_rejected_upload_does_not_spend_the_budget(self):
        pdf = SimpleUploadedFile("bill.pdf", NOT_AN_IMAGE, content_type="application/pdf")
        rejected = self.client.post(reverse("expenses:bill_upload"), {"image": pdf})
        self.assertEqual(rejected.status_code, 200)
        self.assertFalse(BillScan.objects.exists())

        # The budget is still whole: a bad upload is not a worker job.
        self.assertEqual(self.upload_web(1).status_code, 302)

    @patch.object(ratelimit, "SCAN_LIMIT", 1)
    def test_the_limit_is_per_account_not_per_address(self):
        self.assertEqual(self.upload_web(1).status_code, 302)

        # Same test client, i.e. the same address -- a different account's
        # budget must be untouched.
        self.client.force_login(self.bob)
        self.assertEqual(self.upload_web(2).status_code, 302)


class ExportLimitTests(JobLimitTestCase):
    def request_web(self):
        return self.client.post(reverse("expenses:export_create"), {})

    def request_api(self):
        return self.client.post("/api/v1/exports/", {}, content_type="application/json")

    @patch.object(ratelimit, "EXPORT_LIMIT", 2)
    def test_the_page_and_the_api_share_one_budget(self):
        self.assertEqual(self.request_web().status_code, 302)
        self.assertEqual(self.request_api().status_code, 202)

        self.assertEqual(self.request_web().status_code, 429)
        response = self.request_api()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["code"], "rate_limited")
        self.assertEqual(ExportJob.objects.count(), 2)

    @patch.object(ratelimit, "EXPORT_LIMIT", 1)
    def test_the_limit_is_per_account_not_per_address(self):
        self.assertEqual(self.request_web().status_code, 302)

        self.client.force_login(self.bob)
        self.assertEqual(self.request_web().status_code, 302)

    @patch.object(ratelimit, "EXPORT_LIMIT", 1)
    def test_rejected_dates_do_not_spend_the_budget(self):
        bad = self.client.post(
            "/api/v1/exports/", {"start": "not-a-date"}, content_type="application/json"
        )
        self.assertEqual(bad.status_code, 400)

        self.assertEqual(self.request_api().status_code, 202)


class JobBudgetTests(JobLimitTestCase):
    """Taking from the budget is one step: count, then decide from the new total."""

    @patch.object(ratelimit, "SCAN_LIMIT", 2)
    def test_each_take_counts_and_decides_at_once(self):
        # No separate "record" step for simultaneous requests to slip between:
        # the third take is refused on its own, whatever else is in flight.
        results = [ratelimit.take_scan(self.alice) for _ in range(3)]

        self.assertEqual(results, [True, True, False])

    @patch.object(ratelimit, "SCAN_LIMIT", 1)
    def test_a_refund_gives_the_unit_back(self):
        self.assertTrue(ratelimit.take_scan(self.alice))
        ratelimit.refund_scan(self.alice)

        self.assertTrue(ratelimit.take_scan(self.alice))
        self.assertFalse(ratelimit.take_scan(self.alice))

    def test_a_refund_after_the_count_expired_is_harmless(self):
        ratelimit.refund_export(self.alice)

        self.assertTrue(ratelimit.take_export(self.alice))


# --- 4. CSV exports: safe for a spreadsheet to open ------------------------


class CsvSafeTests(SimpleTestCase):
    def test_ordinary_text_is_left_alone(self):
        self.assertEqual(_csv_safe("Groceries"), "Groceries")
        self.assertEqual(_csv_safe(""), "")
        self.assertEqual(_csv_safe("Lunch with Bob"), "Lunch with Bob")

    def test_each_dangerous_leading_character_is_neutralised(self):
        for prefix in ("=", "+", "-", "@", "\t", "\r"):
            cell = f"{prefix}cmd|' /C calc'!A1"
            self.assertEqual(_csv_safe(cell), f"'{cell}")

    def test_the_character_only_matters_at_the_start(self):
        # "Tax - GST" is an ordinary note, not a formula.
        self.assertEqual(_csv_safe("Tax - GST"), "Tax - GST")


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class CsvExportSanitizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def test_a_formula_like_category_and_note_open_as_text_but_amount_stays_numeric(self):
        category = Category.objects.create(user=self.alice, name="=cmd|calc")
        Expense.objects.create(
            user=self.alice,
            category=category,
            amount=Decimal("42.50"),
            spent_on=date(2026, 9, 1),
            note="@SUM(1)",
        )
        # A second row whose amount is negative -- still a plain number.
        Expense.objects.create(
            user=self.alice,
            category=category,
            amount=Decimal("7.00"),
            spent_on=date(2026, 9, 2),
            note="-DDE/calc",
        )

        job = ExportJob.objects.create(
            user=self.alice, start=date(2026, 9, 1), end=date(2026, 9, 30)
        )
        _write_csv(job)

        content = job.file.read().decode("utf-8")

        self.assertIn("'=cmd|calc", content)
        self.assertIn("'@SUM(1)", content)
        self.assertIn("'-DDE/calc", content)
        # The category cell is quoted-safe on every row, not only the first.
        self.assertEqual(content.count("'=cmd|calc"), 2)
        # Amounts are never quote-prefixed, and a negative one still reads
        # as a plain signed number.
        self.assertIn(",42.50,", content)
        self.assertIn(",7.00,", content)
        self.assertNotIn("'42.50", content)
        self.assertNotIn("'7.00", content)

    def test_an_ordinary_export_is_untouched(self):
        category = Category.objects.create(user=self.alice, name="Food")
        Expense.objects.create(
            user=self.alice,
            category=category,
            amount=Decimal("100.00"),
            spent_on=date(2026, 9, 1),
            note="Lunch",
        )

        job = ExportJob.objects.create(
            user=self.alice, start=date(2026, 9, 1), end=date(2026, 9, 30)
        )
        _write_csv(job)

        content = job.file.read().decode("utf-8")
        self.assertIn("Food", content)
        self.assertIn("Lunch", content)
        self.assertNotIn("'Food", content)
        self.assertNotIn("'Lunch", content)
