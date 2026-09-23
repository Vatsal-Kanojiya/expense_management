"""The extraction boundary.

extract_bill is the only thing the rest of the app calls. It returns a
plain ExtractedBill or raises ExtractionError -- no provider type ever
crosses this line.

Stub for now: always the fake provider. S4 replaces the body with a
registry lookup keyed on settings.BILL_SCAN_PROVIDER.
"""

from .providers.fake import FakeProvider
from .types import ExtractedBill

__all__ = ["ACCEPTED_MIME_TYPES", "MAX_UPLOAD_SIZE", "extract_bill"]

# The one place these are defined -- the upload form and (from S4) the
# dispatcher both validate against these, so the accepted shape is never
# stated twice.
ACCEPTED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # bytes


def extract_bill(data: bytes, mime_type: str) -> ExtractedBill:
    return FakeProvider().extract(data, mime_type)
