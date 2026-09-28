"""Refuses a password that has already appeared in a public data breach.

Roadmap A2 (`docs/SECURITY_ROADMAP.md`). Django's own
``CommonPasswordValidator`` rejects ~20,000 common passwords, but a
password can be strong -- long, no dictionary word, nothing predictable --
and still be worthless, because it is sitting in a credential-stuffing
list from someone else's breach.

**k-anonymity, not "send us your password".** Have I Been Pwned's range
API exists precisely so a caller never has to disclose the password (or
even the whole hash) to find out. Only the first five hex characters of
the password's SHA-1 leave this server; the response is every known-breach
hash sharing that prefix (typically several hundred), and the match is
made locally against the remaining 35 characters. The service the ideal
Pwned Passwords API 3 documents at https://haveibeenpwned.com/API/v3#PwnedPasswords.

**Fails open.** A password rule that only sometimes applies, because an
outage happened to coincide with someone's registration, is a rule this
project would rather relax than let fail a sign-up on this server's own
unreliability. If the API cannot be reached, the password is accepted and
a warning is logged -- never the password, never its hash, only that the
check could not be made.
"""

import hashlib
import logging

import requests
from django.conf import settings
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

RANGE_API_URL = "https://api.pwnedpasswords.com/range/{prefix}"
REQUEST_TIMEOUT = 3


class PwnedPasswordValidator:
    """See the module docstring for the k-anonymity request and fail-open rule."""

    def validate(self, password, user=None):
        if not getattr(settings, "PWNED_PASSWORDS_ENABLED", True):
            return

        digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()  # noqa: S324
        prefix, suffix = digest[:5], digest[5:]

        try:
            response = requests.get(
                RANGE_API_URL.format(prefix=prefix),
                headers={"Add-Padding": "true"},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except Exception:
            # Network error, timeout, non-2xx -- all the same response:
            # the check could not be made, so it does not block sign-up.
            # exc_info, not the exception's own message repeated into
            # detail: some HTTP client errors echo the request back,
            # and the request line here carries no password, only
            # a 5-character prefix, but there is no reason to rely on
            # that being true of every future exception type this can
            # raise.
            logger.warning("Pwned Passwords check failed; accepting the password", exc_info=True)
            return

        # Each line is "SUFFIX:COUNT". Add-Padding fills the response with
        # extra, real-looking lines whose COUNT is 0 -- padding to obscure
        # the true match count from anyone watching response size on the
        # wire. Those never match a real breach count and are skipped.
        for line in response.text.splitlines():
            found_suffix, _, count = line.partition(":")
            if found_suffix == suffix and count.strip() != "0":
                raise ValidationError(
                    "This password has appeared in a known data breach. Choose a different one.",
                    code="password_breached",
                )

    def get_help_text(self):
        return "Your password can't be one that has appeared in a known data breach."
