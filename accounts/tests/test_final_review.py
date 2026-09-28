"""The whole-branch security review: what fell between the passes."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from accounts import ratelimit
from accounts.checks import shared_cache_for_rate_limits

PASSWORD = "Str0ng-Enough-Pass"


def cache_backend(backend):
    return override_settings(CACHES={"default": {"BACKEND": backend}})


class SharedCacheCheckTests(SimpleTestCase):
    """The rate limits only hold when every worker counts in one place."""

    def test_a_per_process_cache_is_flagged(self):
        for backend in (
            "django.core.cache.backends.locmem.LocMemCache",
            "django.core.cache.backends.dummy.DummyCache",
        ):
            with self.subTest(backend=backend), cache_backend(backend):
                ids = [w.id for w in shared_cache_for_rate_limits(None)]

                self.assertEqual(ids, ["accounts.W001"])

    @cache_backend("django.core.cache.backends.redis.RedisCache")
    def test_a_shared_cache_passes(self):
        self.assertEqual(shared_cache_for_rate_limits(None), [])


@cache_backend("django.core.cache.backends.locmem.LocMemCache")
class PasswordChangeLimitIsPerAccountTests(TestCase):
    """Wrong current passwords count per account, whichever address they come from."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = get_user_model().objects.create_user("alice", "a@example.com", PASSWORD)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)

    def change(self, old, address):
        return self.client.post(
            "/api/v1/auth/password/change/",
            {
                "old_password": old,
                "new_password": "An0ther-Good-Pass",
                "new_password_confirm": "An0ther-Good-Pass",
            },
            content_type="application/json",
            REMOTE_ADDR=address,
        )

    @patch.object(ratelimit, "PASSWORD_CHANGE_LIMIT", 2)
    def test_moving_to_another_address_does_not_reset_the_count(self):
        self.assertEqual(self.change("wrong-1", "198.51.100.1").status_code, 400)
        self.assertEqual(self.change("wrong-2", "198.51.100.2").status_code, 400)

        self.assertEqual(self.change(PASSWORD, "198.51.100.3").status_code, 429)
