"""The extraction boundary.

extract_bill is the only thing the rest of the app calls. It returns a
plain ExtractedBill or raises ExtractionError -- no provider type ever
crosses this line.
"""

from django.conf import settings

from .errors import ExtractionError
from .registry import get_provider
from .types import ExtractedBill

__all__ = ["ACCEPTED_MIME_TYPES", "MAX_UPLOAD_SIZE", "extract_bill"]

# The one place these are defined -- the upload form (expenses/forms.py)
# and this dispatcher both validate against these, so the accepted shape
# is never stated twice.
ACCEPTED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # bytes


def extract_bill(data: bytes, mime_type: str) -> ExtractedBill:
    # Checked again here, not only in the form: extract_bill is the whole
    # package's contract, and a caller that is not the upload form (a
    # management command, a future API) gets the same guarantee.
    if mime_type not in ACCEPTED_MIME_TYPES:
        raise ExtractionError(f"Unsupported image type: {mime_type!r}")
    if len(data) > MAX_UPLOAD_SIZE:
        raise ExtractionError("Image is larger than the 5 MB limit")

    provider_name = settings.BILL_SCAN_PROVIDER
    provider = get_provider(provider_name)
    # .get(), not [] -- "fake" has no entry in BILL_SCAN_MODELS (it has no
    # real model to name), and must not KeyError on the everyday default.
    model = settings.BILL_SCAN_MODELS.get(provider_name, "")

    return provider.extract(data, mime_type, model)
