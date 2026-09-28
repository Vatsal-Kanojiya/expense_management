"""A structured trail of security-relevant events -- logins, password
changes, verification, deletion -- for after-the-fact review.

Known gap, closed here (roadmap A3): only failed logins were ever logged,
and only to a log file (``django.security``, accounts/views.py) that
nobody queries. Sign-ins and failures, password changes and resets, token
revocations, verification and account deletion now land in one table
(``accounts.SecurityEvent``) with who, when, from where and under which
request.

**Never raises.** Recording an event happens on the side of a request that
is trying to do something else -- sign a user in, delete an account. A bug
here, or the database being briefly unavailable, must never turn into a
500 for the thing the user actually asked for, so every failure is caught
and logged instead of propagated.

**Never a secret.** ``detail`` is free-form JSON a caller can enrich an
event with, and it is tempting to reach for "just log the token so we can
see what happened" -- don't. Passwords, tokens, codes and hashes never
belong in a table admins can browse.
"""

import ipaddress
import logging

from django.db import transaction

from .models import SecurityEvent
from .ratelimit import client_ip

logger = logging.getLogger(__name__)


def record(event, request=None, user=None, username="", **detail):
    """Append one row to the security event trail.

    ``username`` is a snapshot, not a live lookup: pass it explicitly for
    an attempt that may not name a real account (a failed login, a
    password-reset request for an unknown address); left out, it is filled
    from ``user`` when one is given. ``**detail`` becomes the event's
    ``detail`` JSON -- small, structured, and never anything secret.
    """
    if not username and user is not None:
        username = user.get_username()

    ip = None
    request_id = ""
    if request is not None:
        # Imported here, not at module level: config.middleware imports
        # nothing from accounts, so there is no real cycle, but importing
        # it lazily keeps this module usable (e.g. in a shell) without
        # pulling in the middleware stack for the common case where no
        # request is passed at all.
        from config.middleware import get_request_id

        ip = _valid_ip(client_ip(request))
        request_id = get_request_id()

    try:
        # Its own savepoint: on Postgres a failed statement aborts the
        # whole surrounding transaction (account deletion runs in one), so
        # catching the error is only enough if the failure is rolled back
        # to here first.
        with transaction.atomic():
            SecurityEvent.objects.create(
                event=event,
                user=user,
                username=username[:150],
                ip=ip,
                request_id=request_id,
                detail=detail,
            )
    except Exception:
        logger.warning("Failed to record security event %r", event, exc_info=True)


def _valid_ip(value):
    """``value`` if it is an IP address, else ``None``.

    client_ip() answers "unknown" when a request has no address, and a
    forwarded header can carry anything. The column is a real IP type on
    Postgres, which refuses such a value -- and the whole event with it.
    """
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None
