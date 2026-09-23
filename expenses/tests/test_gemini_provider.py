"""The Gemini provider, per S6 of docs/HANDOFF_BILL_SCAN.md.

The google-genai SDK client is mocked throughout -- no network in tests
(G12). Real SDK response types are used for candidates/finish_reason so
the tests exercise the SDK's actual enum values, not a stand-in.
"""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from google.genai import types
from google.genai.errors import ClientError, ServerError

from expenses.extraction.errors import ExtractionError
from expenses.extraction.providers.gemini import GeminiProvider

RAW_BILL = {
    "merchant": "Test Cafe",
    "bill_date": "2026-09-05",
    "total": "450.00",
    "lines": [{"name": "Coffee", "amount": "150.00"}, {"name": "Sandwich", "amount": "250.00"}],
    "tax": "50.00",
    "category_hint": "food",
    "confidence": 0.9,
}


def _response(finish_reason=types.FinishReason.STOP, text=None):
    return SimpleNamespace(
        candidates=[SimpleNamespace(finish_reason=finish_reason)],
        text=text,
    )


def _client_error(status_code):
    return ClientError(status_code, {"message": "boom", "status": "ERROR"}, response=None)


class GeminiProviderTests(SimpleTestCase):
    @patch("expenses.extraction.providers.gemini.genai.Client")
    def test_gemini_builds_an_image_block_and_returns_normalized_bill(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _response(text=json.dumps(RAW_BILL))
        mock_client_cls.return_value = mock_client

        bill = GeminiProvider().extract(b"fake-image-bytes", "image/jpeg", "gemini-2.5-flash-lite")

        call_kwargs = mock_client.models.generate_content.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "gemini-2.5-flash-lite")
        image_part = call_kwargs["contents"][0]
        self.assertEqual(image_part.inline_data.mime_type, "image/jpeg")
        self.assertEqual(image_part.inline_data.data, b"fake-image-bytes")

        self.assertEqual(bill.merchant, "Test Cafe")
        self.assertEqual(bill.total, Decimal("450.00"))
        self.assertEqual(len(bill.lines), 2)
        self.assertEqual(bill.provider, "gemini")

    @patch("expenses.extraction.providers.gemini.genai.Client")
    def test_gemini_refusal_becomes_extraction_error(self, mock_client_cls):
        # A parseable body alongside SAFETY proves it's the finish_reason
        # check raising, not the separate "no text" guard doing it by accident.
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _response(
            finish_reason=types.FinishReason.SAFETY, text=json.dumps(RAW_BILL)
        )
        mock_client_cls.return_value = mock_client

        with self.assertRaises(ExtractionError):
            GeminiProvider().extract(b"data", "image/jpeg", "gemini-2.5-flash-lite")

    @patch("expenses.extraction.providers.gemini.genai.Client")
    def test_gemini_rate_limit_is_reraised_for_retry(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = _client_error(429)
        mock_client_cls.return_value = mock_client

        with self.assertRaises(ClientError):
            GeminiProvider().extract(b"data", "image/jpeg", "gemini-2.5-flash-lite")

    @patch("expenses.extraction.providers.gemini.genai.Client")
    def test_gemini_server_error_is_reraised_for_retry(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = ServerError(
            500, {"message": "down", "status": "ERROR"}, response=None
        )
        mock_client_cls.return_value = mock_client

        with self.assertRaises(ServerError):
            GeminiProvider().extract(b"data", "image/jpeg", "gemini-2.5-flash-lite")

    @patch("expenses.extraction.providers.gemini.genai.Client")
    def test_gemini_bad_request_becomes_extraction_error_not_retried(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = _client_error(400)
        mock_client_cls.return_value = mock_client

        with self.assertRaises(ExtractionError):
            GeminiProvider().extract(b"data", "image/jpeg", "gemini-2.5-flash-lite")

    @patch("expenses.extraction.providers.gemini.genai.Client")
    def test_gemini_max_tokens_becomes_extraction_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _response(
            finish_reason=types.FinishReason.MAX_TOKENS, text=json.dumps(RAW_BILL)
        )
        mock_client_cls.return_value = mock_client

        with self.assertRaises(ExtractionError):
            GeminiProvider().extract(b"data", "image/jpeg", "gemini-2.5-flash-lite")

    @patch("expenses.extraction.providers.gemini.genai.Client")
    def test_gemini_invalid_json_becomes_extraction_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _response(text="not json")
        mock_client_cls.return_value = mock_client

        with self.assertRaises(ExtractionError):
            GeminiProvider().extract(b"data", "image/jpeg", "gemini-2.5-flash-lite")
