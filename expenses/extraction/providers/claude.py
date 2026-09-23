"""The Claude provider.

Written against python/claude-api/README.md (client init, vision content
blocks, stop reasons, error classes) and tool-use.md (structured outputs)
in the claude-api skill, per this plan's G11 -- nothing here is guessed.
"""

import base64
import json

import anthropic

from ..errors import ExtractionError
from ..normalize import to_extracted_bill
from ..prompt import JSON_SCHEMA, PROMPT
from ..types import ExtractedBill

# The response is one small JSON object -- a few hundred tokens at most --
# so a generous-but-bounded ceiling catches a runaway response without the
# 16000-token default this skill recommends for open-ended replies.
MAX_TOKENS = 2048


class ClaudeProvider:
    name = "claude"

    def extract(self, data: bytes, mime_type: str, model: str) -> ExtractedBill:
        client = anthropic.Anthropic()
        image_b64 = base64.standard_b64encode(data).decode("utf-8")

        try:
            response = client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": mime_type,
                                    "data": image_b64,
                                },
                            },
                            {"type": "text", "text": PROMPT},
                        ],
                    }
                ],
                output_config={"format": {"type": "json_schema", "schema": JSON_SCHEMA}},
            )
        except (
            anthropic.AuthenticationError,
            anthropic.PermissionDeniedError,
            anthropic.NotFoundError,
            anthropic.BadRequestError,
        ) as exc:
            # Not transient -- a bad key, a bad model name, or a request
            # Claude rejects outright will fail identically on retry.
            raise ExtractionError(f"Claude rejected the request: {exc}") from exc
        except (anthropic.RateLimitError, anthropic.APIConnectionError):
            # Transient -- let scan_bill's autoretry_for handle it.
            raise
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise
            raise ExtractionError(f"Claude API error: {exc}") from exc

        if response.stop_reason == "refusal":
            raise ExtractionError("Claude declined to read this bill")
        if response.stop_reason == "max_tokens":
            raise ExtractionError("Claude's response was cut off before finishing")

        text = next((block.text for block in response.content if block.type == "text"), None)
        if text is None:
            raise ExtractionError("Claude returned no text to parse")

        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ExtractionError(f"Claude returned invalid JSON: {exc}") from exc

        return to_extracted_bill(raw, "claude")
