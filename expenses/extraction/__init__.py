"""The extraction boundary.

extract_bill is the only thing the rest of the app calls. It returns a
plain ExtractedBill or raises ExtractionError -- no provider type ever
crosses this line.

Stub for now: always the fake provider. S4 replaces the body with a
registry lookup keyed on settings.BILL_SCAN_PROVIDER.
"""

from .providers.fake import FakeProvider
from .types import ExtractedBill

__all__ = ["extract_bill"]


def extract_bill(data: bytes, mime_type: str) -> ExtractedBill:
    return FakeProvider().extract(data, mime_type)
