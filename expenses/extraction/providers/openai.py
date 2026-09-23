"""The OpenAI provider.

Written against the installed openai SDK's own source (its README's
structured-output example targets `json_object`, the old unstructured
mode -- `text.format.type: "json_schema"` needs
`ResponseFormatTextJSONSchemaConfigParam`, only in the installed package's type defs) plus
`Response`'s own fields (`status`, `incomplete_details`, `output_text`),
per this plan's G11. Nothing here is guessed. Error classes mirror
Claude's one-for-one -- both SDKs split rate limits into their own class.
"""

import base64
import json

import openai

from ..errors import ExtractionError
from ..normalize import to_extracted_bill
from ..prompt import JSON_SCHEMA, PROMPT
from ..types import ExtractedBill

# max_output_tokens counts reasoning tokens as well as the visible answer
# (see its docstring in the SDK), and the default gpt-5-mini is a reasoning
# model. Low effort keeps the reasoning short -- this is transcription, not
# problem solving -- and the ceiling leaves room for it on top of the small
# JSON answer. Hitting the ceiling is an "incomplete" response, which is an
# ExtractionError and never retried, so erring low here fails scans for good.
REASONING_EFFORT = "low"
MAX_OUTPUT_TOKENS = 4096


class OpenAIProvider:
    name = "openai"

    def extract(self, data: bytes, mime_type: str, model: str) -> ExtractedBill:
        client = openai.OpenAI()
        image_b64 = base64.standard_b64encode(data).decode("utf-8")

        try:
            response = client.responses.create(
                model=model,
                max_output_tokens=MAX_OUTPUT_TOKENS,
                reasoning={"effort": REASONING_EFFORT},
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": PROMPT},
                            {
                                "type": "input_image",
                                "image_url": f"data:{mime_type};base64,{image_b64}",
                            },
                        ],
                    }
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "extracted_bill",
                        "schema": JSON_SCHEMA,
                        "strict": True,
                    }
                },
            )
        except (
            openai.AuthenticationError,
            openai.PermissionDeniedError,
            openai.NotFoundError,
            openai.BadRequestError,
        ) as exc:
            # Not transient -- a bad key, a bad model name, or a request
            # OpenAI rejects outright will fail identically on retry.
            raise ExtractionError(f"OpenAI rejected the request: {exc}") from exc
        except (openai.RateLimitError, openai.APIConnectionError):
            # Transient -- let scan_bill's autoretry_for handle it.
            raise
        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                raise
            raise ExtractionError(f"OpenAI API error: {exc}") from exc

        if response.status == "failed":
            message = response.error.message if response.error else "unknown error"
            raise ExtractionError(f"OpenAI failed to generate a response: {message}")

        if response.status == "incomplete":
            reason = response.incomplete_details.reason if response.incomplete_details else None
            if reason == "content_filter":
                raise ExtractionError("OpenAI declined to read this bill")
            raise ExtractionError("OpenAI's response was cut off before finishing")

        for item in response.output:
            if getattr(item, "type", None) == "message":
                for block in item.content:
                    if getattr(block, "type", None) == "refusal":
                        raise ExtractionError("OpenAI declined to read this bill")

        text = response.output_text
        if not text:
            raise ExtractionError("OpenAI returned no text to parse")

        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ExtractionError(f"OpenAI returned invalid JSON: {exc}") from exc

        return to_extracted_bill(raw, "openai")
