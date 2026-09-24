"""Security pass 2 (docs/HANDOVER.md): files in and out of the app.

Each item lands in its own commit; this file grows alongside them, in the
order HANDOVER.md lists the items. So far: verifying a bill photo's real
type, and refusing an oversized upload as early as Django allows.
"""

from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from config.middleware import MaxUploadSizeMiddleware
from expenses.extraction import (
    ACCEPTED_MIME_TYPES,
    IMAGE_EXTENSIONS,
    MAX_UPLOAD_SIZE,
    sniff_image_type,
)
from expenses.models import BillScan

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
