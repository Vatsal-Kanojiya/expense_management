"""Sign in with Google (docs/design/GOOGLE_SIGNIN.md).

Off unless ``GOOGLE_OAUTH_CLIENT_ID`` is set. Two functions do the work, used
by both the API (``accounts/api.py``) and the web page (``accounts/views.py``)
so the rules live once:

* :func:`verify_id_token` checks Google's signature, audience and issuer on
  an ID token, and requires ``email_verified``.
* :func:`find_or_create_user` matches or creates the local account for a
  verified email, exactly as the design describes -- active account signs
  in, an unverified one is activated (Google has just proved the address),
  a deactivated verified one is refused, and no match creates a new account
  through the same path sign-up uses.

Both are wrapped by :func:`sign_in_with_google`, which is what callers use:
one round trip from a credential to a user, recording the right
``SecurityEvent`` either way. Any failure anywhere in it collapses to one
generic :class:`GoogleSignInError`, logged without the token itself.
"""

import logging
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from expenses.models import Participant

from . import audit

logger = logging.getLogger(__name__)

User = get_user_model()

# Google documents both forms as valid issuers for an ID token.
ALLOWED_ISSUERS = ("accounts.google.com", "https://accounts.google.com")

# What Django usernames allow (UnicodeUsernameValidator): letters, digits
# and @/./+/-/_. Stripped down further to plain ASCII word characters plus
# the punctuation the validator accepts, so an email's local part becomes a
# clean username instead of tripping the form's own validation later.
_USERNAME_CLEAN_RE = re.compile(r"[^\w.@+-]")
_USERNAME_MAX_LENGTH = 150


class GoogleSignInError(Exception):
    """Refused: a bad token, an unverified email, or a deactivated account.

    Deliberately a single class with no detail attached -- the design calls
    for one generic refusal on any failure, so a caller never needs (and
    the API/web layer never accidentally exposes) which case it was.
    """


def google_signin_enabled():
    """Whether Sign in with Google is switched on at all."""
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID)


def verify_id_token(credential):
    """Return the verified email from a Google ID token, or raise.

    Uses ``google.oauth2.id_token.verify_oauth2_token``, which checks the
    signature against Google's published keys, the audience (our client
    id) and expiry. ``iss`` and ``email_verified`` are checked here on top,
    since the library does not enforce either.
    """
    try:
        payload = google_id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            audience=settings.GOOGLE_OAUTH_CLIENT_ID,
        )
    except Exception as exc:
        # Every failure the library can raise (bad signature, expired,
        # wrong audience, malformed token, a network error reaching
        # Google's key endpoint) collapses to the same refusal. Logged by
        # exception type only, with no traceback and no exception message
        # -- `credential` is a bearer credential for the account it names,
        # no different from a password, and some verifier errors are
        # documented to echo back part of the offending value.
        logger.warning("Google ID token verification failed: %s", type(exc).__name__)
        raise GoogleSignInError from None

    if payload.get("iss") not in ALLOWED_ISSUERS:
        logger.warning("Google ID token had an unexpected issuer")
        raise GoogleSignInError

    if not payload.get("email_verified"):
        raise GoogleSignInError

    email = payload.get("email")
    if not email:
        raise GoogleSignInError

    return email.strip().lower()


def _username_from_email(email):
    """A username from the email's local part, cleaned and de-duplicated."""
    local = email.split("@", 1)[0]
    cleaned = _USERNAME_CLEAN_RE.sub("", local)[:_USERNAME_MAX_LENGTH] or "user"

    candidate = cleaned
    suffix = 1
    while User.objects.filter(username=candidate).exists():
        suffix += 1
        tail = str(suffix)
        candidate = f"{cleaned[: _USERNAME_MAX_LENGTH - len(tail)]}{tail}"

    return candidate


@transaction.atomic
def _create_user(email):
    """A new, active account for a Google sign-in, through sign-up's own path.

    Active at once (Google has verified the address), with
    ``email_verified_at`` set and no usable password -- the account can
    only be reached through Google until a password is set. ``Participant``
    self-row creation mirrors ``SignUpView.form_valid``/``SignupView``, so
    this new user has everything a normal sign-up gives it.
    """
    user = User(
        username=_username_from_email(email),
        email=email,
        is_active=True,
        email_verified_at=timezone.now(),
    )
    user.set_unusable_password()
    user.save()
    Participant.get_or_create_self(user)
    return user


def find_or_create_user(email):
    """Match ``email`` to an account, or create one. Returns ``(user, created)``.

    Matching is case-insensitive and, since the database's own uniqueness
    on ``email`` is case-sensitive (accounts/forms.py), more than one row
    can share an email differing only in case -- so every candidate is
    checked rather than assuming the first one found is the right one.
    """
    candidates = list(User.objects.filter(email__iexact=email))

    active = next((u for u in candidates if u.is_active), None)
    if active is not None:
        return active, False

    unverified = next(
        (u for u in candidates if not u.is_active and u.email_verified_at is None), None
    )
    if unverified is not None:
        # Google has just proved this address, which is exactly what the
        # mailed link would have proved -- so this activates the account
        # the same way clicking that link does.
        unverified.is_active = True
        unverified.email_verified_at = timezone.now()
        unverified.save(update_fields=["is_active", "email_verified_at"])
        return unverified, False

    deactivated = next(
        (u for u in candidates if not u.is_active and u.email_verified_at is not None), None
    )
    if deactivated is not None:
        # A verified account someone (the owner, or an admin) deactivated.
        # Refused, as a password login would be -- Google's proof of the
        # address is not a reason to override that.
        raise GoogleSignInError

    return _create_user(email), True


def sign_in_with_google(credential, request=None):
    """Verify ``credential`` and resolve it to a local account.

    Returns ``(user, created)`` on success. Records ``google_login_failed``
    on any refusal and re-raises :class:`GoogleSignInError`;
    ``google_login_succeeded`` (and, for a new account, ``signed_up`` with
    ``detail={"via": "google"}``) on success. The caller still owns what
    happens next -- issuing tokens/a session directly, or stopping at the
    MFA ticket step for an account with two-step sign-in on.
    """
    try:
        email = verify_id_token(credential)
        user, created = find_or_create_user(email)
    except GoogleSignInError:
        audit.record("google_login_failed", request=request)
        raise

    if created:
        audit.record("signed_up", request=request, user=user, via="google")
    audit.record("google_login_succeeded", request=request, user=user)

    return user, created
