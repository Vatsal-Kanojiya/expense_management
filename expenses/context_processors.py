"""Values every page needs, without every view passing them.

The base template's navigation shows how many people currently owe the
user. Without this, each of the nine views rendering base.html would have
to put it in its context, and the one that forgets renders a nav with a
missing badge.

**A context processor runs on every template render** -- error pages, the
admin, templates that never look at the value. Anything it does is a tax on
every page in the project, and the first version of this one walked every
expense to count balances. That added four to six queries to every request
and broke three pinned query counts, which is the tax arriving on schedule.

So this one never computes anything. It reads a cached value and shows the
badge if it is there. The dashboard and the balances page already compute
balances for their own reasons and populate it as a side effect, so the
number appears after the first visit and is never worth a query of its own.
"""

from django.core.cache import cache

from .cache import owed_count_key


def nav_summary(request):
    user = getattr(request, "user", None)

    if user is None or not user.is_authenticated:
        return {}

    # cache.get, never a computation. A miss means no badge, not a query.
    return {"nav_owed_count": cache.get(owed_count_key(user.pk))}
