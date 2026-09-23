"""The default provider. No network, no keys, no cost.

Every environment that has not set BILL_SCAN_PROVIDER runs on this, which is
what keeps the feature working in development and in CI with nothing
configured.
"""

from decimal import Decimal

from ..types import ExtractedBill, ExtractedLine


class FakeProvider:
    name = "fake"

    def extract(self, data: bytes, mime_type: str) -> ExtractedBill:
        # Fixed on purpose -- deterministic, no clock, no randomness, so a
        # test asserting on this result cannot flake.
        return ExtractedBill(
            merchant="Test Cafe",
            total=Decimal("450.00"),
            lines=[
                ExtractedLine(name="Coffee", amount=Decimal("150.00")),
                ExtractedLine(name="Sandwich", amount=Decimal("250.00")),
            ],
            tax=Decimal("50.00"),
            category_hint="food",
            confidence=0.9,
            provider="fake",
        )
