"""Caching the dashboard, and the two ways it can go wrong.

**Wrong one: caching the page.** ``@cache_page`` keys on the URL. Every
signed-in user requests the same ``/`` and gets whatever the first one put
there, so one person's spending totals are served to another. It is one
decorator, it looks harmless, and it is a data breach. There is a test that
demonstrates it before rejecting it.

**Wrong two: forgetting to invalidate.** A cached aggregate is a second
copy of data that is still changing underneath it. Every key here carries
the user's id *and* a version stamp that any write bumps, so a stale entry
is never read -- it is orphaned and expires on its own.

The version stamp is what makes invalidation cheap. Deleting the right keys
would mean knowing every date range anyone has ever looked at; bumping one
integer makes all of them unreachable at once.
"""

from django.core.cache import cache

# Long, because entries are made unreachable by a version bump rather than
# waited out. The timeout is only a backstop for writes that bypass
# bump_version -- the admin, a shell session, a data migration. See
# DECISIONS D11 for why that backstop exists instead of signals.
SUMMARY_TIMEOUT = 15 * 60

VERSION_TIMEOUT = None  # never expires on its own


def _version_key(user_id):
    return f"expenses:v:{user_id}"


def version(user_id):
    """The user's current cache generation.

    ``get_or_set`` rather than get-then-set: two requests arriving together
    would otherwise both see a miss and write different stamps, and the one
    that lost would read entries written under the other.
    """
    return cache.get_or_set(_version_key(user_id), 1, VERSION_TIMEOUT)


def bump_version(user_id):
    """Make every cached summary for this user unreachable.

    ``incr`` is atomic on Redis, so concurrent writers cannot land on the
    same number. It raises when the key is absent, which is not an error
    here: no key means nothing was ever cached, so there is nothing to
    invalidate.
    """
    try:
        cache.incr(_version_key(user_id))
    except ValueError:
        cache.set(_version_key(user_id), 1, VERSION_TIMEOUT)


def summary_key(user_id, start, end):
    """A key nobody else can collide with.

    The user id is in the key because the value is that user's money. The
    date range is in it because the value depends on it. The version makes
    the whole family disposable.
    """
    return f"expenses:summary:{user_id}:{version(user_id)}:{start:%Y%m%d}:{end:%Y%m%d}"


def cached_summary(user, start, end, build):
    """Return a cached summary, building it on a miss.

    Deliberately not ``cache.get_or_set(key, build)``: that would be
    shorter and would hide the miss, and the tests need to count how often
    ``build`` actually runs.

    This does nothing about a stampede. If the entry expires while a
    hundred requests are in flight, all hundred call ``build``. The honest
    fix is a short lock around the rebuild, and it is not worth the
    machinery at this scale -- but the shape of the problem is the point.
    """
    key = summary_key(user.pk, start, end)
    value = cache.get(key)

    if value is None:
        value = build()
        cache.set(key, value, SUMMARY_TIMEOUT)

    return value
