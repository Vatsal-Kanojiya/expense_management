"""The OpenAI provider, per S6 of docs/HANDOFF_BILL_SCAN.md.

The openai SDK client is mocked throughout -- no network in tests (G12).
"""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx2
from django.test import SimpleTestCase
from openai import APIConnectionError, AuthenticationError, RateLimitError

from expenses.extraction.errors import ExtractionError
from expenses.extraction.providers.openai import OpenAIProvider

RAW_BILL = {
    "merchant": "Test Cafe",
    "bill_date": "2026-09-05",
    "total": "450.00",
    "lines": [{"name": "Coffee", "amount": "150.00"}, {"name": "Sandwich", "amount": "250.00"}],
    "tax": "50.00",
    "category_hint": "food",
    "confidence": 0.9,
}


def _response(status="completed", output_text=None, incomplete_reason=None, refused=False):
    incomplete_details = SimpleNamespace(reason=incomplete_reason) if incomplete_reason else None
    if refused:
        output = [SimpleNamespace(type="message", content=[SimpleNamespace(type="refusal")])]
    else:
        output = [SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text")])]
    return SimpleNamespace(
        status=status,
        error=None,
        incomplete_details=incomplete_details,
        output=output,
        output_text=output_text,
    )


def _api_error(error_cls, message="boom", status_code=429):
    request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx2.Response(status_code, request=request)
    return error_cls(message, response=response, body=None)


class OpenAIProviderTests(SimpleTestCase):
    @patch("expenses.extraction.providers.openai.openai.OpenAI")
    def test_openai_builds_an_image_block_and_returns_normalized_bill(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_client.responses.create.return_value = _response(output_text=json.dumps(RAW_BILL))
        mock_openai_cls.return_value = mock_client

        bill = OpenAIProvider().extract(b"fake-image-bytes", "image/jpeg", "gpt-5-mini")

        call_kwargs = mock_client.responses.create.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "gpt-5-mini")
        image_block = call_kwargs["input"][0]["content"][1]
        self.assertEqual(image_block["type"], "input_image")
        self.assertEqual(
            image_block["image_url"], "data:image/jpeg;base64,ZmFrZS1pbWFnZS1ieXRlcw=="
        )

        self.assertEqual(bill.merchant, "Test Cafe")
        self.assertEqual(bill.total, Decimal("450.00"))
        self.assertEqual(len(bill.lines), 2)
        self.assertEqual(bill.provider, "openai")

    @patch("expenses.extraction.providers.openai.openai.OpenAI")
    def test_openai_refusal_becomes_extraction_error(self, mock_openai_cls):
        # A parseable output_text alongside a refusal content block proves
        # it's the refusal check raising, not the "no text" guard by accident.
        mock_client = MagicMock()
        mock_client.responses.create.return_value = _response(
            refused=True, output_text=json.dumps(RAW_BILL)
        )
        mock_openai_cls.return_value = mock_client

        with self.assertRaises(ExtractionError):
            OpenAIProvider().extract(b"data", "image/jpeg", "gpt-5-mini")

    @patch("expenses.extraction.providers.openai.openai.OpenAI")
    def test_openai_rate_limit_is_reraised_for_retry(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_client.responses.create.side_effect = _api_error(RateLimitError, status_code=429)
        mock_openai_cls.return_value = mock_client

        with self.assertRaises(RateLimitError):
            OpenAIProvider().extract(b"data", "image/jpeg", "gpt-5-mini")

    @patch("expenses.extraction.providers.openai.openai.OpenAI")
    def test_openai_connection_error_is_reraised_for_retry(self, mock_openai_cls):
        mock_client = MagicMock()
        request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
        mock_client.responses.create.side_effect = APIConnectionError(request=request)
        mock_openai_cls.return_value = mock_client

        with self.assertRaises(APIConnectionError):
            OpenAIProvider().extract(b"data", "image/jpeg", "gpt-5-mini")

    @patch("expenses.extraction.providers.openai.openai.OpenAI")
    def test_openai_auth_error_becomes_extraction_error_not_retried(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_client.responses.create.side_effect = _api_error(AuthenticationError, status_code=401)
        mock_openai_cls.return_value = mock_client

        with self.assertRaises(ExtractionError):
            OpenAIProvider().extract(b"data", "image/jpeg", "gpt-5-mini")

    @patch("expenses.extraction.providers.openai.openai.OpenAI")
    def test_openai_incomplete_response_becomes_extraction_error(self, mock_openai_cls):
        # A parseable body alongside "incomplete" proves it's the status
        # check raising, not the separate "no text" guard doing it by accident.
        mock_client = MagicMock()
        mock_client.responses.create.return_value = _response(
            status="incomplete",
            incomplete_reason="max_output_tokens",
            output_text=json.dumps(RAW_BILL),
        )
        mock_openai_cls.return_value = mock_client

        with self.assertRaises(ExtractionError):
            OpenAIProvider().extract(b"data", "image/jpeg", "gpt-5-mini")

    @patch("expenses.extraction.providers.openai.openai.OpenAI")
    def test_openai_invalid_json_becomes_extraction_error(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_client.responses.create.return_value = _response(output_text="not json")
        mock_openai_cls.return_value = mock_client

        with self.assertRaises(ExtractionError):
            OpenAIProvider().extract(b"data", "image/jpeg", "gpt-5-mini")
