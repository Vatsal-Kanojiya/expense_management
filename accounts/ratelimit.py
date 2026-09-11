"""A cache-backed rate limiter for the two endpoints that need one.

Known issue 15, open since session 5: login and password reset accepted
unlimited attempts. Credential stuffing was unthrottled and anyone could
flood an inbox with reset mail by posting the same address repeatedly.

**Why this is hand-written rather than django-axes.** Axes is the right
answer for production -- it has lockout policies, an admin, and a decade of
edge cases handled. Forty lines here make the mechanism visible: a counter
per key, a window, and a decision about what the key should be. That choice
is the part worth understanding, and it is the part a library hides.

**Keying is the design.** Three options, none of them complete:

* **By IP alone** -- one office, one NAT, one blocked building. Also useless
  against a botnet with a thousand addresses.
* **By username alone** -- an attacker locks any account out of its own
  login by failing it deliberately. That is a denial of service handed over
  free.
* **By both** -- what this does. Slows a single source against a single
  account, which is the shape of credential stuffing, without letting
  either dimension be weaponised alone.

None of them stop a distributed attack. That needs a reputation service,
and the honest statement is that this raises the cost rather than closing
the door.
"""

from django.core.cache import cache

# Deliberately generous. A person who has forgotten which password they use
# will legitimately fail four or five times, and locking them out teaches
# them to hate the product rather than teaching an attacker anything.
LOGIN_LIMIT = 10
LOGIN_WINDOW = 15 * 60

# Tighter, because there is no legitimate reason to ask for five reset
# mails in an hour and every one of them lands in someone else's inbox.
RESET_LIMIT = 5
RESET_WINDOW = 60 * 60


def client_ip(request):
    """The caller's address, trusting X-Forwarded-For only when configured.

    Behind a proxy, REMOTE_ADDR is the proxy. In front of one,
    X-Forwarded-For is whatever the client typed. Reading the header
    unconditionally is how a rate limiter becomes decorative: the attacker
    sends a different value each request.

    So the header is read only when SECURE_PROXY_SSL_HEADER is configured,
    which is this project's existing signal that a trusted proxy is in
    front. The left-most entry is the original client; the proxy appends.
    """
    from django.conf import settings

    if getattr(settings, "SECURE_PROXY_SSL_HEADER", None):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR", "unknown")


def _key(scope, request, identifier):
    # Lower-cased and truncated: "Alice" and "alice" are the same account,
    # and an unbounded identifier is an unbounded cache key.
    identifier = (identifier or "").strip().lower()[:150]
    return f"ratelimit:{scope}:{client_ip(request)}:{identifier}"


def is_limited(scope, request, identifier, limit, window):
    """Whether this caller has already used up its attempts.

    Read-only, so it can be asked before doing the work without consuming
    an attempt itself.
    """
    return (cache.get(_key(scope, request, identifier)) or 0) >= limit


def record_attempt(scope, request, identifier, window):
    """Count one attempt against this caller.

    The window is fixed, not sliding: the counter expires as a whole rather
    than ageing entry by entry. A determined caller can therefore get up to
    2x the limit across a window boundary. A sliding window costs a sorted
    set per key and is not worth it here, but the gap should be known
    rather than assumed away.

    add() then incr(), because incr() raises on a missing key and set()
    would reset the expiry on every attempt -- which would make the window
    restart forever and the limit unreachable.
    """
    key = _key(scope, request, identifier)
    cache.add(key, 0, window)

    try:
        return cache.incr(key)
    except ValueError:
        # The key expired between add() and incr(). Rare, and the right
        # response is to treat this attempt as the first of a new window.
        cache.set(key, 1, window)
        return 1


def clear(scope, request, identifier):
    """Forget a caller's attempts, on success.

    Without this, ten successful logins in a window would lock a user out,
    which punishes exactly the wrong person.
    """
    cache.delete(_key(scope, request, identifier))
