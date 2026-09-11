import tempfile

from django.conf import settings
from django.test.runner import DiscoverRunner


class FastTestRunner(DiscoverRunner):
    """Test runner that swaps two production-only settings for fast ones.

    Django's default PBKDF2 hasher is deliberately slow — that slowness is
    the security property, since it is what makes brute-forcing a stolen
    password database expensive. In tests it buys nothing and costs
    everything: every create_user and every login pays the same price.

    On this suite that is 20.5s versus 0.5s, a 40x difference, and it grows
    with every test that touches a user.

    MD5 is used here *only* because it is fast and this runner is never
    active outside the test process. Never put this in settings.PASSWORD_HASHERS.

    The alternative is a settings split (config/settings/test.py). This is
    the lighter option while the project has a single settings module.

    The second swap is the static files storage. Phase 11 turned on
    WhiteNoise's CompressedManifestStaticFilesStorage, which hashes and
    gzips every file it is asked for. That is exactly right in production
    and pure overhead in tests: the suite went from 3.6s to 14.6s on the
    commit that enabled it, for no assertion's benefit.

    It also makes tests fail for an unrelated reason. Manifest storage
    raises when asked for a file that is not in the manifest, so any test
    rendering a template with {% static %} fails unless collectstatic has
    been run first.

    The third swap is STATIC_ROOT, and it is the expensive one. WhiteNoise
    builds its index of every collected file when the middleware is
    constructed, and the test client constructs a fresh handler per client
    instance -- so a suite with many TestCase classes rescans hundreds of
    files hundreds of times. Pointing STATIC_ROOT at an empty directory
    keeps the middleware in the chain, and in its real position, while
    making that scan free. Removing the middleware instead would be faster
    still and would stop the ordering assertion testing anything.

    Measured on this suite: 3.6s before phase 11, 14.6s with WhiteNoise
    unmodified, 3.9s with these swaps.

    The fourth swap is the cache, and it is about correctness rather than
    speed. Django does not clear the cache between tests, so a cached
    dashboard survives into the next test and makes its query count wrong
    -- which is exactly how phase 14 broke an unrelated assertion. Caching
    is therefore off by default and tests that are *about* the cache turn
    it back on with override_settings. A test that caches by accident is a
    test that passes for a reason nobody chose.
    """

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
        settings.STORAGES = {
            **settings.STORAGES,
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
        settings.STATIC_ROOT = tempfile.mkdtemp(prefix="test-static-")
        settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
