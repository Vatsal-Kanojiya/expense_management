"""The one shape every provider returns, and the app ever sees.

Frozen and stdlib-only on purpose: nothing in expenses/ that consumes an
ExtractedBill needs to import a provider's SDK, and nothing here can be
mutated after a provider builds it.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ExtractedLine:
    name: str
    amount: Decimal


@dataclass(frozen=True)
class ExtractedBill:
    merchant: str = ""
    bill_date: date | None = None
    total: Decimal | None = None
    lines: list[ExtractedLine] = field(default_factory=list)
    tax: Decimal = Decimal("0")
    category_hint: str = ""
    confidence: float = 0.0
    provider: str = ""
