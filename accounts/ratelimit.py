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

# Failed logins from one address across *all* usernames. The per-username
# key above never counts one guess against each of many accounts; this cap
# does. High enough for an office behind one NAT, low enough to matter.
LOGIN_IP_LIMIT = 50
LOGIN_IP_WINDOW = 15 * 60

# Sign-ups from one address. Each one sends an email to an address the
# caller chose, so this protects third parties as much as the database.
SIGNUP_LIMIT = 10
SIGNUP_WINDOW = 60 * 60

# Wrong current passwords per account. Changing a password needs the old
# one precisely so that a stolen session cannot lock the owner out; that
# only holds if the old one cannot be guessed at leisure.
PASSWORD_CHANGE_LIMIT = 5
PASSWORD_CHANGE_WINDOW = 15 * 60

# Bill scans and CSV exports per account (security pass 2). Both occupy a
# background worker for the length of the job, and a scan calls a paid
# vision API when BILL_SCAN_PROVIDER is a real one -- unlike the limits
# above, this is not only about abuse, it is about one account not being
# able to run the worker pool, or the bill, unbounded. Generous: a person
# reviewing a stack of receipts or re-running a few exports in an hour
# should never feel this.
SCAN_LIMIT = 30
SCAN_WINDOW = 60 * 60

EXPORT_LIMIT = 20
EXPORT_WINDOW = 60 * 60


def client_ip(request):
    """The caller's address, as far as the deployment can vouch for it.

    With no proxy in front (TRUSTED_PROXY_COUNT = 0), REMOTE_ADDR is the
    client, and X-Forwarded-For is ignored: it is whatever the client typed.

    Behind N trusted proxies, each appends the address it received the
    request from, so the entry N places from the right is the one the
    outermost trusted proxy saw. Everything to its left arrived with the
    request and is the client's to invent. Reading the left-most entry --
    as this function did until security pass 1 -- let any caller pick the
    key its attempts were counted under.
    """
    from django.conf import settings

    proxies = getattr(settings, "TRUSTED_PROXY_COUNT", 0)
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if proxies > 0 and forwarded:
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            return hops[-min(proxies, len(hops))]

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


def _increment(key, window):
    """Count one attempt against whatever `key` names, and return the total.

    The window is fixed, not sliding: the counter expires as a whole rather
    than ageing entry by entry. A determined caller can therefore get up to
    2x the limit across a window boundary. A sliding window costs a sorted
    set per key and is not worth it here, but the gap should be known
    rather than assumed away.

    add() then incr(), because incr() raises on a missing key and set()
    would reset the expiry on every attempt -- which would make the window
    restart forever and the limit unreachable.
    """
    cache.add(key, 0, window)

    try:
        return cache.incr(key)
    except ValueError:
        # The key expired between add() and incr(). Rare, and the right
        # response is to treat this attempt as the first of a new window.
        cache.set(key, 1, window)
        return 1


def record_attempt(scope, request, identifier, window):
    """Count one attempt against this caller (see _increment)."""
    return _increment(_key(scope, request, identifier), window)


def clear(scope, request, identifier):
    """Forget a caller's attempts, on success.

    Without this, ten successful logins in a window would lock a user out,
    which punishes exactly the wrong person.
    """
    cache.delete(_key(scope, request, identifier))


# --- The login guard, shared by every login door -------------------------
#
# The web page, the API and the admin site each take a password. One guard
# for all three means attempts through any of them count against the same
# budgets, and a door added later cannot forget half the rules.


def login_blocked(request, username):
    """Whether this attempt must be refused before the password is checked."""
    return is_limited("login", request, username, LOGIN_LIMIT, LOGIN_WINDOW) or is_limited(
        "login-ip", request, "", LOGIN_IP_LIMIT, LOGIN_IP_WINDOW
    )


def record_login_failure(request, username):
    record_attempt("login", request, username, LOGIN_WINDOW)
    record_attempt("login-ip", request, "", LOGIN_IP_WINDOW)


def clear_login(request, username):
    """Forget this username's failures. The per-address count stays."""
    clear("login", request, username)


# --- Per-user job limits, shared by the web pages and the API ------------
#
# Keyed on the account, not the address: the login guards above are about
# who is knocking, but a scan or an export is something a *signed-in*
# account does to the worker pool (and, for a scan, to a paid API) no
# matter which network it does it from. Keying this by IP the way the
# login guards are would let the same account reset its budget by moving
# to another address, or would lock an office's shared address on one
# person's behalf -- both wrong for a per-account cost.


def _user_key(scope, user_id):
    return f"ratelimit:{scope}:user:{user_id}"


def take_user_budget(scope, user_id, limit, window):
    """Spend one unit of this account's budget for `scope`; False if none is left.

    Counts first and decides from the new total, in one cache operation,
    rather than reading the count and adding to it later: two requests
    sent at the same moment would otherwise both read the same old count
    and both be let through, however many were sent.
    """
    return _increment(_user_key(scope, user_id), window) <= limit


def refund_user_budget(scope, user_id):
    """Give back a unit spent on a request that then made no job."""
    try:
        cache.decr(_user_key(scope, user_id))
    except ValueError:
        # Expired in between: nothing to give back.
        pass


def take_scan(user):
    return take_user_budget("scan", user.pk, SCAN_LIMIT, SCAN_WINDOW)


def refund_scan(user):
    refund_user_budget("scan", user.pk)


def take_export(user):
    return take_user_budget("export", user.pk, EXPORT_LIMIT, EXPORT_WINDOW)


def refund_export(user):
    refund_user_budget("export", user.pk)
