"""The one prompt and the one JSON schema every provider sends.

One copy so Claude, Gemini and OpenAI are all being asked the same question
in the same shape -- if the prompt drifted per provider, "switch the
provider" would silently also mean "change what gets extracted".
"""

PROMPT = """You are reading a photo of a bill or receipt, most likely from India. \
Extract what is on it into the JSON shape described below. Amounts are in \
rupees.

Rules:
- "lines" are the items purchased. Never put a tax, GST, CGST, SGST, \
service charge or tip line in "lines" -- all of those go into "tax" \
instead, summed together.
- If a field is unreadable or absent, return an empty value for it (an \
empty string, null, or an empty list) rather than guessing.
- "category_hint" is a single common-sense word for what kind of bill this \
is (e.g. "food", "groceries", "travel", "fuel", "shopping", "utilities"), \
or an empty string if you are not confident.
- "confidence" is your own estimate, 0 to 1, of how much of this you read \
correctly.
- Amounts must be plain decimal strings, e.g. "450.00", not numbers -- no \
currency symbol, no thousands separator.
- "bill_date" must be an ISO date (YYYY-MM-DD) if you can read one, else \
null."""

# Field names mirror ExtractedBill (types.py), minus "provider" -- that is
# filled in by the caller, never by the model. Every amount is a string
# (see PROMPT above): models round floats, and strings are what
# normalize.to_extracted_bill expects to parse.
JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "merchant": {"type": "string"},
        "bill_date": {"type": ["string", "null"]},
        "total": {"type": ["string", "null"]},
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "amount": {"type": "string"},
                },
                "required": ["name", "amount"],
            },
        },
        "tax": {"type": "string"},
        "category_hint": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["merchant", "bill_date", "total", "lines", "tax", "category_hint", "confidence"],
}
