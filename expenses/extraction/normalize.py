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

_DATE_FORMATS = (
    "%Y-%m-%d",  # ISO -- what the prompt actually asks providers for
    "%d/%m/%Y",  # Indian order before American: 05/09/2026 is 5 September
    "%d-%m-%Y",
)


def to_extracted_bill(raw: dict, provider: str) -> ExtractedBill:
    lines = []
    for entry in (raw.get("lines") or [])[:MAX_LINES]:
        amount = _parse_amount(entry.get("amount"))
        name = str(entry.get("name") or "").strip()
        if amount is None or amount <= 0 or not name:
            continue
        lines.append(ExtractedLine(name=name, amount=amount))

    tax = _parse_amount(raw.get("tax"))

    return ExtractedBill(
        merchant=str(raw.get("merchant") or "").strip(),
        bill_date=_parse_date(raw.get("bill_date")),
        total=_parse_amount(raw.get("total")),
        lines=lines,
        tax=tax if tax is not None else Decimal("0"),
        category_hint=str(raw.get("category_hint") or "").strip(),
        confidence=_clamp_confidence(raw.get("confidence")),
        provider=provider,
    )


def _parse_amount(value):
    """A decimal string, tolerant of what a model tends to send back.

    Negative and unparseable amounts return None rather than raising -- the
    caller drops a line or leaves a total unset, never crashes on one bad
    field in an otherwise readable bill.
    """
    if value is None:
        return None

    cleaned = str(value).strip().replace("₹", "").replace(",", "").replace(" ", "")
    if not cleaned:
        return None

    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None

    if amount < 0:
        return None

    return amount.quantize(Decimal("0.01"))


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
