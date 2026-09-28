"""The extraction boundary.

extract_bill is the only thing the rest of the app calls. It returns a
plain ExtractedBill or raises ExtractionError -- no provider type ever
crosses this line.
"""

from django.conf import settings

from .errors import ExtractionError
from .registry import get_provider
from .types import ExtractedBill

__all__ = [
    "ACCEPTED_MIME_TYPES",
    "IMAGE_EXTENSIONS",
    "MAX_UPLOAD_SIZE",
    "extract_bill",
    "sniff_image_type",
]

# The one place these are defined -- the upload form (expenses/forms.py)
# and this dispatcher both validate against these, so the accepted shape
# is never stated twice.
ACCEPTED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # bytes

# The extension to save each accepted type under, once sniff_image_type has
# said which one a file really is. Keyed the same way as ACCEPTED_MIME_TYPES
# so the two cannot list a different set of formats by accident.
IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def sniff_image_type(header: bytes) -> str | None:
    """What these bytes actually are, judged by the format's own signature.

    A browser's declared Content-Type, and a filename's extension, are both
    whatever the client chose to send -- trivial to spoof by renaming a file
    or crafting the request by hand. This checks the bytes every decoder for
    the format requires at the start, which is what BillScanForm verifies an
    upload against instead of trusting either of those.

    Only the twelve bytes a WebP signature needs are ever read; JPEG and PNG
    need fewer. Returns None, not KeyError, for anything else -- callers
    treat "not a recognised image" as one case, not three.
    """
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    return None


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
