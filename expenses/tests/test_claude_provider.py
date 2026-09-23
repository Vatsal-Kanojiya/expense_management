"""The Claude provider, per S5 of docs/HANDOFF_BILL_SCAN.md.

The anthropic SDK client is mocked throughout -- no network in tests (G12).
"""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx2
from anthropic import APIConnectionError, AuthenticationError, RateLimitError
from django.test import SimpleTestCase

from expenses.extraction.errors import ExtractionError
from expenses.extraction.providers.claude import ClaudeProvider

RAW_BILL = {
    "merchant": "Test Cafe",
    "bill_date": "2026-09-05",
    "total": "450.00",
    "lines": [{"name": "Coffee", "amount": "150.00"}, {"name": "Sandwich", "amount": "250.00"}],
    "tax": "50.00",
    "category_hint": "food",
    "confidence": 0.9,
}


def _response(stop_reason="end_turn", text=None):
    content = [] if text is None else [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(stop_reason=stop_reason, content=content)


def _api_error(error_cls, message="boom", status_code=429):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status_code, request=request)
    return error_cls(message, response=response, body=None)


class ClaudeProviderTests(SimpleTestCase):
    @patch("expenses.extraction.providers.claude.anthropic.Anthropic")
    def test_claude_builds_an_image_block_and_returns_normalized_bill(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _response(text=json.dumps(RAW_BILL))
        mock_anthropic_cls.return_value = mock_client

        bill = ClaudeProvider().extract(b"fake-image-bytes", "image/jpeg", "claude-sonnet-5")

        call_kwargs = mock_client.messages.create.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "claude-sonnet-5")
        image_block = call_kwargs["messages"][0]["content"][0]
        self.assertEqual(image_block["type"], "image")
        self.assertEqual(image_block["source"]["media_type"], "image/jpeg")
        self.assertEqual(image_block["source"]["data"], "ZmFrZS1pbWFnZS1ieXRlcw==")

        self.assertEqual(bill.merchant, "Test Cafe")
        self.assertEqual(bill.total, Decimal("450.00"))
        self.assertEqual(len(bill.lines), 2)
        self.assertEqual(bill.provider, "claude")

    @patch("expenses.extraction.providers.claude.anthropic.Anthropic")
    def test_claude_refusal_becomes_extraction_error(self, mock_anthropic_cls):
        # A parseable body alongside "refusal" proves it's the stop_reason
        # check raising, not the separate "no text" guard doing it by accident.
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _response(
            stop_reason="refusal", text=json.dumps(RAW_BILL)
        )
        mock_anthropic_cls.return_value = mock_client

        with self.assertRaises(ExtractionError):
            ClaudeProvider().extract(b"data", "image/jpeg", "claude-sonnet-5")

    @patch("expenses.extraction.providers.claude.anthropic.Anthropic")
    def test_claude_rate_limit_is_reraised_for_retry(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _api_error(RateLimitError, status_code=429)
        mock_anthropic_cls.return_value = mock_client

        with self.assertRaises(RateLimitError):
            ClaudeProvider().extract(b"data", "image/jpeg", "claude-sonnet-5")

    @patch("expenses.extraction.providers.claude.anthropic.Anthropic")
    def test_claude_connection_error_is_reraised_for_retry(self, mock_anthropic_cls):
        mock_client = MagicMock()
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        mock_client.messages.create.side_effect = APIConnectionError(request=request)
        mock_anthropic_cls.return_value = mock_client

        with self.assertRaises(APIConnectionError):
            ClaudeProvider().extract(b"data", "image/jpeg", "claude-sonnet-5")

    @patch("expenses.extraction.providers.claude.anthropic.Anthropic")
    def test_claude_auth_error_becomes_extraction_error_not_retried(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _api_error(AuthenticationError, status_code=401)
        mock_anthropic_cls.return_value = mock_client

        with self.assertRaises(ExtractionError):
            ClaudeProvider().extract(b"data", "image/jpeg", "claude-sonnet-5")

    @patch("expenses.extraction.providers.claude.anthropic.Anthropic")
    def test_claude_max_tokens_becomes_extraction_error(self, mock_anthropic_cls):
        # A parseable body alongside "max_tokens" proves it's the stop_reason
        # check raising, not the separate "no text" guard doing it by accident.
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _response(
            stop_reason="max_tokens", text=json.dumps(RAW_BILL)
        )
        mock_anthropic_cls.return_value = mock_client

        with self.assertRaises(ExtractionError):
            ClaudeProvider().extract(b"data", "image/jpeg", "claude-sonnet-5")

    @patch("expenses.extraction.providers.claude.anthropic.Anthropic")
    def test_claude_invalid_json_becomes_extraction_error(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _response(text="not json")
        mock_anthropic_cls.return_value = mock_client

        with self.assertRaises(ExtractionError):
            ClaudeProvider().extract(b"data", "image/jpeg", "claude-sonnet-5")
