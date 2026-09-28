"""The second step, shared by every way in -- the web login page and the
API (``docs/design/MFA.md``). Both hand a signed **ticket** back and forth
between "password accepted" and "code accepted", and both check a code the
same way, so that logic lives once, here.

No session and no tokens exist while a ticket is outstanding: it names a
user and expires in ``TICKET_MAX_AGE`` seconds, and it stops working the
moment the password changes (its signature covers a fingerprint of the
current password hash, not the hash itself).
"""

import hashlib

from django.core import signing

from . import audit, ratelimit
from .models import RecoveryCode, TOTPDevice

TICKET_SALT = "accounts.mfa-login"
TICKET_MAX_AGE = 300


def _password_fingerprint(user):
    # A hash of the password hash, not the hash itself -- this only ever
    # needs to answer "has the password changed since?", never to verify a
    # password on its own, so nothing about it needs to be reversible or
    # even a proper password hash.
    return hashlib.sha256(user.password.encode()).hexdigest()


def make_ticket(user):
    """A signed ticket for ``user``, good for ``TICKET_MAX_AGE`` seconds."""
    return signing.dumps(
        {"user_id": user.pk, "pwfp": _password_fingerprint(user)}, salt=TICKET_SALT
    )


def user_for_ticket(ticket, user_model):
    """The user a ticket names, or ``None`` if it is missing, tampered
    with, expired, or was issued before a password change since undid it.
    """
    try:
        data = signing.loads(ticket, salt=TICKET_SALT, max_age=TICKET_MAX_AGE)
    except signing.BadSignature:
        return None

    try:
        user = user_model.objects.get(pk=data.get("user_id"))
    except user_model.DoesNotExist:
        return None

    if not user.is_active or _password_fingerprint(user) != data.get("pwfp"):
        return None
    return user


def verify_code(user, code, request=None):
    """Try ``code`` as this account's current TOTP code, then as one of its
    recovery codes. Records the outcome and, on success, clears the
    per-account attempt count.

    Returns ``True`` on success, ``False`` on a wrong code, or ``None`` if
    the account has already used up its attempts for this window -- the
    caller decides how to render each case.
    """
    if ratelimit.mfa_blocked(user):
        return None

    used_recovery_code = False
    ok = False

    device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
    if device is not None and device.verify(code):
        ok = True
    elif RecoveryCode.try_use(user, code):
        ok = True
        used_recovery_code = True

    if ok:
        ratelimit.clear_mfa(user)
        if used_recovery_code:
            audit.record("recovery_code_used", request=request, user=user)
        audit.record("mfa_challenge_passed", request=request, user=user)
    else:
        ratelimit.record_mfa_failure(user)
        audit.record("mfa_challenge_failed", request=request, user=user)

    return ok


def check_for_change(user, code, request=None, password=None, recovery_allowed=True):
    """The guard for changing two-step settings: disabling, new recovery codes.

    Returns ``None`` when the change may go ahead, or why not: ``"blocked"``
    (too many recent failures), ``"password"`` or ``"code"``.

    These actions are reached with a signed-in session, which is exactly
    what someone who found an unlocked laptop or a stolen token has. Without
    a limit they could guess the password and then the six-digit code until
    two-step sign-in was off. So wrong passwords count against the
    per-account password-change budget, and wrong codes against the same
    per-account budget as the sign-in step.
    """
    if ratelimit.mfa_blocked(user) or (
        password is not None and ratelimit.password_change_blocked(user)
    ):
        return "blocked"

    if password is not None and not user.check_password(password):
        ratelimit.record_password_change_failure(user)
        return "password"

    device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
    ok = device is not None and device.verify(code)
    used_recovery_code = False
    if not ok and recovery_allowed:
        ok = used_recovery_code = RecoveryCode.try_use(user, code)

    if not ok:
        ratelimit.record_mfa_failure(user)
        audit.record("mfa_challenge_failed", request=request, user=user)
        return "code"

    ratelimit.clear_mfa(user)
    if password is not None:
        ratelimit.clear_password_change(user)
    if used_recovery_code:
        audit.record("recovery_code_used", request=request, user=user)
    return None
