"""The provider-agnostic parts of bill scanning: normalisation and the
registry that picks a provider by name.

No database needed for any of this -- SimpleTestCase, like test_splitting.py
and test_error_pages.py.
"""

import json
import sys
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from expenses.extraction import extract_bill
from expenses.extraction.checks import review_warnings
from expenses.extraction.errors import ExtractionError
from expenses.extraction.normalize import to_extracted_bill
from expenses.extraction.registry import get_provider
from expenses.extraction.types import ExtractedBill, ExtractedLine

RAW_BILL = {
    "merchant": "Test Cafe",
    "bill_date": "2026-09-05",
    "total": "450.00",
    "lines": [{"name": "Coffee", "amount": "150.00"}],
    "tax": "50.00",
    "category_hint": "food",
    "confidence": 0.9,
}


class NormalizeTests(SimpleTestCase):
    def test_normalize_parses_rupee_strings_with_commas(self):
        bill = to_extracted_bill(
            {
                "merchant": "Test Cafe",
                "bill_date": None,
                "total": "₹1,234.50",
                "lines": [],
                "tax": "0",
                "category_hint": "",
                "confidence": 0.5,
            },
            provider="fake",
        )

        self.assertEqual(bill.total, Decimal("1234.50"))

    def test_normalize_reads_indian_date_order(self):
        bill = to_extracted_bill(
            {
                "merchant": "",
                "bill_date": "05/09/2026",
                "total": None,
                "lines": [],
                "tax": "0",
                "category_hint": "",
                "confidence": 0,
            },
            provider="fake",
        )

        # 05/09/2026 is 5 September, not 9 May: day before month.
        self.assertEqual(bill.bill_date, date(2026, 9, 5))

    def test_normalize_drops_negative_and_junk_amounts(self):
        bill = to_extracted_bill(
            {
                "merchant": "",
                "bill_date": None,
                "total": "-50.00",
                "lines": [
                    {"name": "Valid", "amount": "10.00"},
                    {"name": "Negative", "amount": "-5.00"},
                    {"name": "Junk", "amount": "not a number"},
                ],
                "tax": "not a number either",
                "category_hint": "",
                "confidence": 0.5,
            },
            provider="fake",
        )

        # A negative or unparseable total is dropped, not kept as garbage.
        self.assertIsNone(bill.total)
        # Only the one genuinely valid line survives.
        self.assertEqual(len(bill.lines), 1)
        self.assertEqual(bill.lines[0].name, "Valid")
        # tax has no None state in the contract -- unparseable falls back
        # to zero rather than leaving the field absent.
        self.assertEqual(bill.tax, Decimal("0"))


class RegistryTests(SimpleTestCase):
    def test_unknown_provider_raises_extraction_error(self):
        with self.assertRaises(ExtractionError):
            get_provider("not-a-real-provider")

    def test_registry_does_not_import_unused_providers(self):
        # The point of resolving providers by string path: a server
        # configured for one provider never needs another's SDK installed.
        # A None entry in sys.modules makes that import raise ImportError, so
        # this holds regardless of which earlier test already loaded an SDK.
        blocked = {"anthropic": None, "google.genai": None, "openai": None}
        with patch.dict(sys.modules, blocked):
            provider = get_provider("fake")

        self.assertEqual(provider.name, "fake")


class ProviderToggleTests(SimpleTestCase):
    """One test per real provider, proving BILL_SCAN_PROVIDER actually switches
    which SDK gets called -- the point of the whole registry (S4-S6)."""

    @override_settings(BILL_SCAN_PROVIDER="claude", BILL_SCAN_MODELS={"claude": "claude-sonnet-5"})
    @patch("expenses.extraction.providers.claude.anthropic.Anthropic")
    def test_toggle_selects_claude(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(RAW_BILL))],
        )
        mock_anthropic_cls.return_value = mock_client

        bill = extract_bill(b"data", "image/jpeg")

        self.assertEqual(bill.provider, "claude")

    @override_settings(
        BILL_SCAN_PROVIDER="gemini", BILL_SCAN_MODELS={"gemini": "gemini-2.5-flash-lite"}
    )
    @patch("expenses.extraction.providers.gemini.genai.Client")
    def test_toggle_selects_gemini(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = SimpleNamespace(
            candidates=[SimpleNamespace(finish_reason=None)],
            text=json.dumps(RAW_BILL),
        )
        mock_client_cls.return_value = mock_client

        bill = extract_bill(b"data", "image/jpeg")

        self.assertEqual(bill.provider, "gemini")

    @override_settings(BILL_SCAN_PROVIDER="openai", BILL_SCAN_MODELS={"openai": "gpt-5-mini"})
    @patch("expenses.extraction.providers.openai.openai.OpenAI")
    def test_toggle_selects_openai(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_client.responses.create.return_value = SimpleNamespace(
            status="completed",
            error=None,
            incomplete_details=None,
            output=[SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text")])],
            output_text=json.dumps(RAW_BILL),
        )
        mock_openai_cls.return_value = mock_client

        bill = extract_bill(b"data", "image/jpeg")

        self.assertEqual(bill.provider, "openai")


class ReviewWarningTests(SimpleTestCase):
    """The vendor-agnostic checks. Pure: no database, no provider, fixed today."""

    TODAY = date(2026, 9, 23)

    def _bill(self, **overrides):
        fields = {
            "merchant": "Test Cafe",
            "bill_date": self.TODAY,
            "total": Decimal("450.00"),
            "lines": [
                ExtractedLine(name="Coffee", amount=Decimal("150.00")),
                ExtractedLine(name="Sandwich", amount=Decimal("250.00")),
            ],
            "tax": Decimal("50.00"),
            "category_hint": "food",
            "confidence": 0.9,
            "provider": "claude",
        }
        fields.update(overrides)
        return ExtractedBill(**fields)

    def test_a_consistent_bill_has_no_warnings(self):
        self.assertEqual(review_warnings(self._bill(), self.TODAY), [])

    def test_items_plus_tax_not_matching_total_warns(self):
        warnings = review_warnings(self._bill(total=Decimal("500.00")), self.TODAY)

        self.assertEqual(len(warnings), 1)
        self.assertIn("₹450.00", warnings[0])
        self.assertIn("₹500.00", warnings[0])

    def test_a_round_off_within_one_rupee_does_not_warn(self):
        self.assertEqual(review_warnings(self._bill(total=Decimal("451.00")), self.TODAY), [])

    def test_a_bill_with_no_lines_skips_the_arithmetic_check(self):
        # Lines are optional -- a total-only bill has nothing to add up.
        self.assertEqual(review_warnings(self._bill(lines=[]), self.TODAY), [])

    def test_missing_or_zero_total_warns(self):
        self.assertIn("No bill total", review_warnings(self._bill(total=None), self.TODAY)[0])
        self.assertIn("₹0.00", review_warnings(self._bill(total=Decimal("0.00")), self.TODAY)[0])

    def test_implausible_dates_warn(self):
        future = review_warnings(self._bill(bill_date=date(2026, 10, 1)), self.TODAY)
        stale = review_warnings(self._bill(bill_date=date(2025, 1, 5)), self.TODAY)
        missing = review_warnings(self._bill(bill_date=None), self.TODAY)

        self.assertIn("in the future", future[0])
        self.assertIn("over a year ago", stale[0])
        self.assertIn("No date was read", missing[0])

    def test_missing_merchant_and_low_confidence_warn(self):
        warnings = review_warnings(self._bill(merchant="", confidence=0.2), self.TODAY)

        self.assertEqual(len(warnings), 2)
        self.assertIn("No shop name", warnings[0])
        self.assertIn("unsure", warnings[1])
