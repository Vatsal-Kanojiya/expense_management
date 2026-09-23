"""Which provider class a name resolves to.

Import paths as strings, resolved lazily -- a server configured for
BILL_SCAN_PROVIDER=gemini must not need the anthropic package installed, and
importing every provider up front to build this dict would require exactly
that.
"""

from django.utils.module_loading import import_string

from .errors import ExtractionError

PROVIDERS = {
    "fake": "expenses.extraction.providers.fake.FakeProvider",
    "claude": "expenses.extraction.providers.claude.ClaudeProvider",
    "gemini": "expenses.extraction.providers.gemini.GeminiProvider",
    "openai": "expenses.extraction.providers.openai.OpenAIProvider",
}


def get_provider(name: str):
    """Return a fresh instance of the provider registered under `name`."""
    path = PROVIDERS.get(name)
    if path is None:
        raise ExtractionError(f"Unknown bill-scan provider: {name!r}")

    try:
        provider_class = import_string(path)
    except ImportError as exc:
        # Most likely: the provider's SDK is not installed. That is a
        # deployment problem (a missing dependency for the configured
        # provider), not a bill the model failed to read, but it still has
        # to surface as ExtractionError -- it is the only exception this
        # package's boundary promises to raise.
        raise ExtractionError(f"Bill-scan provider {name!r} is not available: {exc}") from exc

    return provider_class()
