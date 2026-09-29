"""Signed-in devices: at most ``MAX_SIGNED_IN_DEVICES`` per account.

``docs/design/SESSION_LIMITS.md`` is the spec. A "device" is a web session
or an API refresh-token chain; each has one ``SignedInDevice`` row. A
sign-in registers its row and, if the account is then over the limit, ends
the oldest devices (by ``last_seen_at``) until it is not.

Ending a device means ending the real thing the row stands for -- deleting
the ``Session`` row for a web device, blacklisting the ``OutstandingToken``
for an API one -- and recording a ``device_signed_out`` event.

Every function here is safe to call for a user whose records are stale:
``prune`` runs before every count, so a device that simply went away (its
session expired, its token expired or was blacklisted, or its password
changed underneath it) never pushes out a live one.
"""

from django.conf import settings
from django.contrib.auth import HASH_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from . import audit
from .models import SignedInDevice, User

LABEL_LENGTH = 200


def limit():
    """How many devices an account may be signed in on. Never below one."""
    return max(1, int(settings.MAX_SIGNED_IN_DEVICES))


def label_for(request):
    """The User-Agent, truncated -- what the devices list calls a device."""
    if request is None:
        return ""
    return request.META.get("HTTP_USER_AGENT", "")[:LABEL_LENGTH]


# --- Registering -----------------------------------------------------------


def register_web(request, user):
    """Record the web session ``request`` now holds, then enforce the limit.

    Called on ``user_logged_in``, which fires after ``login()`` has cycled
    the session key, so ``request.session.session_key`` is the new one.
    """
    session = getattr(request, "session", None)
    key = getattr(session, "session_key", None)
    if not key:
        return None
    # login() on an already-signed-in session rotates its key; a row left
    # under the old key is the same device, and is dead by now (prune). A row
    # under this very key would be a duplicate of the one made here.
    forget_web(key)
    device = SignedInDevice.objects.create(
        user=user, kind=SignedInDevice.Kind.WEB, session_key=key, label=label_for(request)
    )
    enforce(user, keep=device, request=request)
    return device


def register_api(user, jti, request=None):
    """Record a new refresh-token chain, then enforce the limit."""
    device = SignedInDevice.objects.create(
        user=user, kind=SignedInDevice.Kind.API, refresh_jti=jti, label=label_for(request)
    )
    enforce(user, keep=device, request=request)
    return device


def rotate_api(old_jti, new_jti, user, request=None):
    """A refresh replaced ``old_jti`` with ``new_jti``: one device, one record.

    A token that has no record is one issued before this feature existed
    (nothing else that can still refresh lacks one: ending a device
    blacklists its token). It is registered now, so a chain that predates
    the limit cannot go on outside it for ever.
    """
    moved = SignedInDevice.objects.filter(
        user=user, kind=SignedInDevice.Kind.API, refresh_jti=old_jti
    ).update(refresh_jti=new_jti, last_seen_at=timezone.now())
    if not moved:
        register_api(user, new_jti, request)


def rekey(request, old_key):
    """The session ``old_key`` now has ``request.session.session_key``.

    For ``cycle_key()`` and ``update_session_auth_hash()``, which give a
    live session a new key: without this the current device's record would
    point at a session that no longer exists and be dropped from the count.
    """
    new_key = request.session.session_key
    if old_key and new_key and old_key != new_key:
        SignedInDevice.objects.filter(kind=SignedInDevice.Kind.WEB, session_key=old_key).update(
            session_key=new_key
        )


def cycle_session_key(request):
    """``request.session.cycle_key()``, keeping the device record with it."""
    old_key = request.session.session_key
    request.session.cycle_key()
    rekey(request, old_key)


# --- Forgetting (a normal sign-out) ----------------------------------------


def forget_web(session_key):
    if session_key:
        SignedInDevice.objects.filter(
            kind=SignedInDevice.Kind.WEB, session_key=session_key
        ).delete()


def forget_api(jti):
    if jti:
        SignedInDevice.objects.filter(kind=SignedInDevice.Kind.API, refresh_jti=jti).delete()


def forget_all_api(user):
    """Every API record of ``user``: their tokens were all just revoked."""
    SignedInDevice.objects.filter(user=user, kind=SignedInDevice.Kind.API).delete()


# --- Counting and enforcing ------------------------------------------------


def _session_is_live(session, user):
    """Whether a stored session still signs ``user`` in.

    Existing and unexpired is not enough: changing the password leaves every
    other session's row in place while Django refuses to load them (their
    stored auth hash no longer matches), and those must not count.
    """
    data = session.get_decoded()
    if data.get(SESSION_KEY) != str(user.pk):
        return False
    stored = data.get(HASH_SESSION_KEY, "")
    if constant_time_compare(stored, user.get_session_auth_hash()):
        return True
    return any(
        constant_time_compare(stored, fallback)
        for fallback in user.get_session_auth_fallback_hash()
    )


def prune(user, keep=None, request=None):
    """Drop ``user``'s records whose session or token is already dead.

    Neither ``keep`` (a device being registered right now) nor the session
    ``request`` itself is running under is ever judged: what a session
    holds is not saved until the response goes out, so a key that was just
    rotated, or a hash that was just updated, cannot be checked yet -- and
    a session that is making the request is alive by definition.
    """
    now = timezone.now()
    devices = SignedInDevice.objects.filter(user=user)
    if keep is not None:
        devices = devices.exclude(pk=keep.pk)
    current_key = getattr(getattr(request, "session", None), "session_key", None)
    if current_key:
        devices = devices.exclude(kind=SignedInDevice.Kind.WEB, session_key=current_key)
    devices = list(devices)

    web = [d for d in devices if d.kind == SignedInDevice.Kind.WEB]
    sessions = {
        s.session_key: s
        for s in Session.objects.filter(
            session_key__in=[d.session_key for d in web], expire_date__gt=now
        )
    }
    api = [d for d in devices if d.kind == SignedInDevice.Kind.API]
    live_jtis = set(
        OutstandingToken.objects.filter(
            jti__in=[d.refresh_jti for d in api],
            expires_at__gt=now,
            blacklistedtoken__isnull=True,
        ).values_list("jti", flat=True)
    )

    dead = [
        d.pk
        for d in devices
        if (
            d.kind == SignedInDevice.Kind.WEB
            and not (d.session_key in sessions and _session_is_live(sessions[d.session_key], user))
        )
        or (d.kind == SignedInDevice.Kind.API and d.refresh_jti not in live_jtis)
    ]
    if dead:
        SignedInDevice.objects.filter(pk__in=dead).delete()


def end(device, request=None, reason="limit"):
    """Sign ``device`` out for real, drop its record, and record the event."""
    if device.kind == SignedInDevice.Kind.WEB:
        Session.objects.filter(session_key=device.session_key).delete()
    else:
        # Its access token keeps working until it expires (JWT_ACCESS_MINUTES);
        # what ends here is the ability to refresh.
        for token in OutstandingToken.objects.filter(jti=device.refresh_jti):
            BlacklistedToken.objects.get_or_create(token=token)

    audit.record(
        "device_signed_out",
        request=request,
        user=device.user,
        kind=device.kind,
        label=device.label,
        reason=reason,
    )
    device.delete()


def enforce(user, keep, request=None):
    """End the oldest devices until ``user`` is within the limit.

    ``keep`` -- the device that was just registered -- is never ended, so a
    sign-in always succeeds; it is also the newest, so it would not be
    picked anyway. The user's row is locked for the duration (a no-op on
    SQLite), so two sign-ins racing on Postgres cannot both count the same
    devices and both leave the account one over.
    """
    with transaction.atomic():
        User.objects.select_for_update().filter(pk=user.pk).first()
        prune(user, keep=keep, request=request)
        # Oldest first, explicitly: the order decides which devices are ended.
        devices = list(SignedInDevice.objects.filter(user=user).order_by("last_seen_at", "id"))
        excess = len(devices) - limit()
        for device in [d for d in devices if d.pk != keep.pk][: max(excess, 0)]:
            end(device, request=request)


def live_devices(user, request=None):
    """``user``'s devices after dropping the dead ones, oldest first."""
    prune(user, request=request)
    return list(SignedInDevice.objects.filter(user=user))


def is_current(device, request):
    """Whether ``device`` is the web session making ``request``.

    An API device cannot say which one it is: the access token carries no
    refresh-token id. A request authenticated by bearer token is not the
    web session even if it also sends its cookie.
    """
    if device.kind != SignedInDevice.Kind.WEB or not device.session_key:
        return False
    if getattr(request, "auth", None) is not None:
        return False
    return getattr(request.session, "session_key", None) == device.session_key
