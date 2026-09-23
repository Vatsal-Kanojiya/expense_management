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
from expenses.extraction.errors import ExtractionError
from expenses.extraction.normalize import to_extracted_bill
from expenses.extraction.registry import get_provider

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
        # If "fake" resolving drags in "anthropic", the laziness is fake.
        if "anthropic" in sys.modules:
            self.skipTest("anthropic already imported by another test")

        get_provider("fake")

        self.assertNotIn("anthropic", sys.modules)


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
