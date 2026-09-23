"""Turn a scan's saved result into initial values for the expense form.

Pure and side-effect free so it is testable without a view. scan.result is
exactly what tasks._bill_to_json produced -- JSON-safe strings for every
Decimal and date, never the typed values themselves -- so everything here
parses strings back into what the form actually wants.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from expenses.models import Category, Expense


def initial_from_scan(scan, user):
    """Return (expense_initial, line_item_initials) for one BillScan.

    Never raises on a malformed or partial result -- a scan the model got
    half right should pre-fill what it can, not crash the review page.
    """
    result = scan.result or {}
    initial = {}

    merchant = (result.get("merchant") or "").strip()
    if merchant:
        max_length = Expense._meta.get_field("note").max_length
        initial["note"] = merchant[:max_length]

    total = _to_decimal(result.get("total"))
    if total is not None:
        initial["amount"] = total

    initial["spent_on"] = _to_date(result.get("bill_date")) or timezone.localdate()

    category_hint = (result.get("category_hint") or "").strip()
    if category_hint:
        category = Category.objects.filter(user=user, name__iexact=category_hint).first()
        if category is not None:
            initial["category"] = category

    tax = _to_decimal(result.get("tax"))
    if tax is not None and tax > 0:
        initial["misc_amount"] = tax
        initial["misc_note"] = "Tax / tip (scanned)"

    line_initials = []
    for line in result.get("lines") or []:
        amount = _to_decimal(line.get("amount"))
        if amount is None or amount <= 0:
            continue
        line_initials.append({"name": (line.get("name") or "").strip()[:100], "amount": amount})

    return initial, line_initials


def _to_decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _to_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
