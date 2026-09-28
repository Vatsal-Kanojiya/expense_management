"""RFC 6238 TOTP: the code math only, standard library and Django's own
``settings`` -- no extra dependency (``docs/design/MFA.md``).

Everything that needs the database (which secret belongs to which user,
whether a step has already been used) lives on ``accounts.models.TOTPDevice``
instead; this module only turns a secret and a moment in time into a code,
or a code back into a matched step.
"""

import base64
import hmac
import secrets
import struct
import time
from hashlib import sha1
from urllib.parse import quote

from django.conf import settings

DIGITS = 6
STEP_SECONDS = 30
SECRET_BYTES = 20
# One step either side of "now", so a slow typist or a clock a few seconds
# off is not refused.
WINDOW = 1


def generate_secret():
    """A fresh random secret, base32-encoded without padding."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def _hotp(secret, counter):
    """The 6-digit code for one counter value (RFC 4226)."""
    padded = secret + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded, casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10**DIGITS)).zfill(DIGITS)


def current_step(at=None):
    moment = time.time() if at is None else at
    return int(moment // STEP_SECONDS)


def verify(secret, code, last_used_step, at=None):
    """The step ``code`` matches, or ``None``.

    Checks the current step and one either side (``WINDOW``). A step at or
    before ``last_used_step`` is refused here too, so a caller that forgets
    to also apply the conditional database update still gets no replay --
    but ``TOTPDevice.verify`` is what makes that refusal race-safe; this
    function alone is not (two concurrent calls could both return the same
    step).
    """
    code = "".join((code or "").split())
    if not code.isdigit() or len(code) != DIGITS:
        return None

    step = current_step(at)
    for candidate in range(step - WINDOW, step + WINDOW + 1):
        if candidate <= last_used_step:
            continue
        if hmac.compare_digest(_hotp(secret, candidate), code):
            return candidate
    return None


def otpauth_uri(secret, username, issuer=None):
    """An ``otpauth://totp/...`` URI for an authenticator app to scan."""
    issuer = issuer or getattr(settings, "MFA_ISSUER", "Expense Tracker")
    label = quote(f"{issuer}:{username}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
