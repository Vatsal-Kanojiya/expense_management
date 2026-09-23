"""The Gemini provider.

Written against the installed google-genai SDK's own source (README has no
image + structured-output example that matches this exact SDK version) --
`types.Part.from_bytes`, `GenerateContentConfig.response_json_schema`, and
`google.genai.errors` -- per this plan's G11. Nothing here is guessed.

One shape surprise worth flagging: unlike Claude/OpenAI, google-genai does
not give rate limits their own exception class -- `ClientError` covers
every 4xx (400, 401, 403, 429 alike), so the retryable case is split out by
`.code` instead of by exception type.
"""

import json

from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError

from ..errors import ExtractionError
from ..normalize import to_extracted_bill
from ..prompt import JSON_SCHEMA, PROMPT
from ..types import ExtractedBill

# The response is one small JSON object -- a few hundred tokens at most --
# so a generous-but-bounded ceiling catches a runaway response.
MAX_OUTPUT_TOKENS = 2048


class GeminiProvider:
    name = "gemini"

    def extract(self, data: bytes, mime_type: str, model: str) -> ExtractedBill:
        client = genai.Client()

        try:
            response = client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_bytes(data=data, mime_type=mime_type),
                    PROMPT,
                ],
                config=types.GenerateContentConfig(
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    response_mime_type="application/json",
                    response_json_schema=JSON_SCHEMA,
                ),
            )
        except ClientError as exc:
            if exc.code == 429:
                # Transient -- let scan_bill's autoretry_for handle it.
                raise
            # Not transient -- a bad key, a bad model name, or a request
            # Gemini rejects outright will fail identically on retry.
            raise ExtractionError(f"Gemini rejected the request: {exc}") from exc
        except ServerError:
            # Transient -- let scan_bill's autoretry_for handle it.
            raise

        candidates = response.candidates or []
        finish_reason = candidates[0].finish_reason if candidates else None
        if finish_reason == types.FinishReason.MAX_TOKENS:
            raise ExtractionError("Gemini's response was cut off before finishing")
        if finish_reason in (
            types.FinishReason.SAFETY,
            types.FinishReason.RECITATION,
            types.FinishReason.BLOCKLIST,
            types.FinishReason.PROHIBITED_CONTENT,
        ):
            raise ExtractionError("Gemini declined to read this bill")

        text = response.text
        if not text:
            raise ExtractionError("Gemini returned no text to parse")

        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ExtractionError(f"Gemini returned invalid JSON: {exc}") from exc

        return to_extracted_bill(raw, "gemini")
