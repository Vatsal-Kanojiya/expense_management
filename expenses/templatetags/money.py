"""Money formatting, in one place instead of thirty.

Before this, templates rendered `{{ amount }}` and got whatever str() on a
Decimal produces -- "150.00" in some places, "150" in others depending on
whether the value came from a column or an aggregate. Two of those
inconsistencies were fixed by quantising in Python, which is the wrong
layer: presentation is not the model's job.
"""

from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()

CENT = Decimal("0.01")


@register.filter
def rupees(value):
    """Format a Decimal as ₹1,23,456.78.

    Indian digit grouping, which is not what any locale-free formatter
    produces: the last three digits group together and everything above
    that groups in twos. 1234567 is 12,34,567 and not 1,234,567.

    Returns an em dash for None so templates stop writing
    `{{ x|default:"—" }}` beside every amount and getting "0" for a real
    zero, which is a different statement from "nothing".
    """
    if value is None or value == "":
        return "—"

    try:
        amount = Decimal(value).quantize(CENT)
    except (InvalidOperation, TypeError, ValueError):
        return value

    sign = "-" if amount < 0 else ""
    whole, _, fraction = f"{abs(amount):.2f}".partition(".")

    if len(whole) > 3:
        last_three = whole[-3:]
        rest = whole[:-3]
        # Groups of two, right to left, above the final three.
        groups = [rest[max(index - 2, 0) : index] for index in range(len(rest), 0, -2)]
        whole = ",".join(reversed(groups)) + "," + last_three

    return f"{sign}₹{whole}.{fraction}"


@register.filter
def owed_label(count):
    """Pluralise the nav badge without an {% if %} in the template."""
    if not count:
        return "Balances"
    return f"Balances ({count})"
