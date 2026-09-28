"""Deployment checks for what the rate limits rely on.

Every limit in accounts/ratelimit.py counts in the default cache. A
per-process cache (the local-memory default, or the dummy one) gives each
gunicorn worker its own count, so a limit of 5 becomes 5 per worker, and a
restart forgets them all. Nothing fails loudly: the limits just stop
meaning what they say. compose.yaml sets a shared Redis cache; this check
is for a deployment that does not.
"""

from django.conf import settings
from django.core.checks import Warning, register

PER_PROCESS_CACHES = (
    "django.core.cache.backends.locmem.LocMemCache",
    "django.core.cache.backends.dummy.DummyCache",
)


@register(deploy=True)
def shared_cache_for_rate_limits(app_configs, **kwargs):
    backend = settings.CACHES.get("default", {}).get("BACKEND", "")
    if backend in PER_PROCESS_CACHES:
        return [
            Warning(
                "The default cache is not shared between processes, so rate limits "
                "count per worker and reset on restart.",
                hint="Set CACHE_URL to a shared cache, e.g. rediscache://redis:6379/2.",
                id="accounts.W001",
            )
        ]
    return []
