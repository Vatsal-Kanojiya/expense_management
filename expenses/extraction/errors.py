class ExtractionError(Exception):
    """A bill could not be read.

    The only exception extract_bill raises. A provider translates every
    vendor-specific failure into this one, or lets a transient failure
    propagate as-is so Celery's retry logic runs -- so nothing upstream of
    extract_bill ever needs to know which vendor is behind it.
    """
