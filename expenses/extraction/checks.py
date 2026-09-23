"""Point the reviewer at what the scan most likely got wrong.

Vendor-agnostic on purpose: these read only an ExtractedBill, so they judge
Claude, Gemini, OpenAI and any future provider by the same rules. They never
correct anything -- the review form stays the only path to an expense (G13),
and a warning only tells the user where to look before pressing Save.

Ordered strongest signal first. Arithmetic is the one check that needs no
trust in the model at all; the model's own confidence is the weakest, since
models are often confident and wrong.
"""

from datetime import date, timedelta
from decimal import Decimal

from .types import ExtractedBill

# Rounding on real bills (per-line GST, round-off lines) routinely leaves the
# printed total a rupee away from the sum of its parts.
TOTAL_TOLERANCE = Decimal("1.00")
LOW_CONFIDENCE = 0.5
OLDEST_PLAUSIBLE = timedelta(days=365)


def review_warnings(bill: ExtractedBill, today: date) -> list[str]:
    warnings = []

    if bill.total is None:
        warnings.append("No bill total was read. Enter the amount yourself.")
    elif bill.total == 0:
        warnings.append("The bill total was read as ₹0.00. Check the amount.")
    elif bill.lines:
        parts = sum((line.amount for line in bill.lines), Decimal("0")) + bill.tax
        if abs(parts - bill.total) > TOTAL_TOLERANCE:
            warnings.append(
                f"Items plus tax come to ₹{parts}, but the bill total was read as "
                f"₹{bill.total}. An item or the total may have been misread."
            )

    if bill.bill_date is None:
        warnings.append("No date was read, so it is set to today. Change it if the bill is older.")
    elif bill.bill_date > today:
        warnings.append(f"The date was read as {bill.bill_date:%d %b %Y}, which is in the future.")
    elif today - bill.bill_date > OLDEST_PLAUSIBLE:
        warnings.append(
            f"The date was read as {bill.bill_date:%d %b %Y}, over a year ago. Check the date."
        )

    if not bill.merchant:
        warnings.append("No shop name was read.")

    if bill.confidence < LOW_CONFIDENCE:
        warnings.append("The scanner itself was unsure about this bill. Check every field.")

    return warnings
