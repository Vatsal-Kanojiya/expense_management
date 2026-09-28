"""Turn one provider's raw JSON into a plain ExtractedBill.

Every provider funnels through this -- providers never build an
ExtractedBill themselves. One parser means one place decides what a
malformed amount or an ambiguous date means, instead of three places that
might decide differently.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from .types import ExtractedBill, ExtractedLine

MAX_LINES = 50

# A provider is untrusted input, same as a form field: cap free text before
# it is ever written to BillScan.result, rather than trusting a vision
# model to be economical with tokens. These mirror the fields the text
# eventually lands in -- Expense.note for the merchant, ExpenseItem.name for
# a line -- so a bill that fills every field to the limit still prefills
# cleanly; category_hint is never stored, only matched against an existing
# Category, so its cap only bounds what gets logged and compared.
MAX_TEXT_LENGTH = 255
MAX_LINE_NAME_LENGTH = 100

_DATE_FORMATS = (
    "%Y-%m-%d",  # ISO -- what the prompt actually asks providers for
    "%d/%m/%Y",  # Indian order before American: 05/09/2026 is 5 September
    "%d-%m-%Y",
)


def to_extracted_bill(raw: dict, provider: str) -> ExtractedBill:
    # The schema handed to every provider asks for an object, but nothing
    # stops a model answering with a bare string, a list, or null and still
    # calling that valid JSON. Treating that as an empty bill -- rather than
    # letting the ``.get()`` calls below raise ``AttributeError`` -- keeps
    # the promise this module's docstring makes: one place decides what a
    # malformed *shape* means, not just a malformed value.
    if not isinstance(raw, dict):
        raw = {}

    raw_lines = raw.get("lines")
    if not isinstance(raw_lines, list):
        raw_lines = []

    lines = []
    for entry in raw_lines[:MAX_LINES]:
        if not isinstance(entry, dict):
            continue
        amount = _parse_amount(entry.get("amount"))
        name = str(entry.get("name") or "").strip()[:MAX_LINE_NAME_LENGTH]
        if amount is None or amount <= 0 or not name:
            continue
        lines.append(ExtractedLine(name=name, amount=amount))

    tax = _parse_amount(raw.get("tax"))

    return ExtractedBill(
        merchant=str(raw.get("merchant") or "").strip()[:MAX_TEXT_LENGTH],
        bill_date=_parse_date(raw.get("bill_date")),
        total=_parse_amount(raw.get("total")),
        lines=lines,
        tax=tax if tax is not None else Decimal("0"),
        category_hint=str(raw.get("category_hint") or "").strip()[:MAX_TEXT_LENGTH],
        confidence=_clamp_confidence(raw.get("confidence")),
        provider=provider,
    )


def _parse_amount(value):
    """A decimal string, tolerant of what a model tends to send back.

    Negative and unparseable amounts return None rather than raising -- the
    caller drops a line or leaves a total unset, never crashes on one bad
    field in an otherwise readable bill.

    ``Decimal`` parses "NaN" and "Infinity" without error -- they are not
    malformed input, they are valid IEEE-754-style special values -- but
    neither is a comparable, quantizable amount. Left unchecked, ``amount <
    0`` raises on a NaN and ``.quantize()`` raises on an Infinity (and on an
    ordinary value with an ridiculous exponent, such as "1e400"), which
    turned a bill a model answered oddly into an uncaught
    ``decimal.InvalidOperation`` instead of a dropped field.
    """
    if value is None:
        return None

    cleaned = str(value).strip().replace("₹", "").replace(",", "").replace(" ", "")
    if not cleaned:
        return None

    try:
        amount = Decimal(cleaned)
        if not amount.is_finite():
            return None
        if amount < 0:
            return None
        return amount.quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _parse_date(value):
    if not value:
        return None

    value = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _clamp_confidence(value):
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))
