"""Sign-in limits per account (docs/design/SESSION_LIMITS.md).

Part 1: a cap on wrong passwords per account, whatever the address.
Part 2 (devices) is added further down this file.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from accounts import google, ratelimit
from accounts.models import SecurityEvent

User = get_user_model()
PASSWORD = "Str0ng-Enough-Pass"

with_cache = override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "session-limits-tests",
        }
    }
)


def address(n):
    return f"10.0.{n // 250}.{n % 250 + 1}"


@with_cache
class AccountPasswordCapTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def setUp(self):
        cache.clear()

    def api_login(self, username, password, addr="127.0.0.1"):
        return self.client.post(
            "/api/v1/auth/login/",
            {"username": username, "password": password},
            content_type="application/json",
            REMOTE_ADDR=addr,
        )

    def web_login(self, username, password, addr="127.0.0.1"):
        return self.client.post(
            "/accounts/login/", {"username": username, "password": password}, REMOTE_ADDR=addr
        )

    def fail_from_many_addresses(self, times, username="alice", start=0):
        for n in range(start, start + times):
            self.assertEqual(self.api_login(username, "wrong", address(n)).status_code, 401)

    def test_the_limits_are_twenty_per_fifteen_minutes(self):
        self.assertEqual(ratelimit.LOGIN_ACCOUNT_LIMIT, 20)
        self.assertEqual(ratelimit.LOGIN_ACCOUNT_WINDOW, 15 * 60)

    def test_twenty_failures_from_different_addresses_block_the_next_even_with_the_right_password(
        self,
    ):
        self.fail_from_many_addresses(ratelimit.LOGIN_ACCOUNT_LIMIT)

        # A twenty-second address, which no per-address cap has ever seen.
        response = self.api_login("alice", PASSWORD, address(99))

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["code"], "rate_limited")

    def test_one_failure_fewer_and_the_right_password_still_works(self):
        self.fail_from_many_addresses(ratelimit.LOGIN_ACCOUNT_LIMIT - 1)

        self.assertEqual(self.api_login("alice", PASSWORD, address(99)).status_code, 200)

    def test_the_web_page_and_the_api_share_the_count(self):
        for n in range(10):
            self.api_login("alice", "wrong", address(n))
        for n in range(10, 20):
            self.web_login("alice", "wrong", address(n))

        self.assertEqual(self.web_login("alice", PASSWORD, address(99)).status_code, 429)
        self.assertEqual(self.api_login("alice", PASSWORD, address(98)).status_code, 429)

    def test_the_username_is_matched_without_regard_to_case_or_spaces(self):
        for n in range(20):
            self.api_login("ALICE" if n % 2 else " alice ", "wrong", address(n))

        self.assertEqual(self.api_login("alice", PASSWORD, address(99)).status_code, 429)

    def test_it_counts_only_the_account_that_was_guessed_at(self):
        User.objects.create_user("bob", "bob@example.com", PASSWORD)
        self.fail_from_many_addresses(ratelimit.LOGIN_ACCOUNT_LIMIT)

        self.assertEqual(self.api_login("bob", PASSWORD, address(99)).status_code, 200)

    def test_a_success_clears_it(self):
        self.fail_from_many_addresses(ratelimit.LOGIN_ACCOUNT_LIMIT - 1)
        self.assertEqual(self.api_login("alice", PASSWORD, address(50)).status_code, 200)

        # The count started again: one more failure is nowhere near the cap.
        self.fail_from_many_addresses(ratelimit.LOGIN_ACCOUNT_LIMIT - 1, start=60)
        self.assertEqual(self.api_login("alice", PASSWORD, address(99)).status_code, 200)

    def test_a_blocked_attempt_is_recorded(self):
        self.fail_from_many_addresses(ratelimit.LOGIN_ACCOUNT_LIMIT)

        self.api_login("alice", PASSWORD, address(99))

        event = SecurityEvent.objects.get(event="login_blocked")
        self.assertEqual(event.username, "alice")

    @patch.object(ratelimit, "LOGIN_ACCOUNT_LIMIT", 3)
    def test_the_block_ends_with_the_counter(self):
        self.fail_from_many_addresses(3)
        self.assertEqual(self.api_login("alice", PASSWORD, address(99)).status_code, 429)

        # The counter is set to expire with its window (_increment); when the cache drops it,
        # the block is gone with it.
        cache.delete(ratelimit._account_key("alice"))

        self.assertEqual(self.api_login("alice", PASSWORD, address(99)).status_code, 200)

    @override_settings(GOOGLE_OAUTH_CLIENT_ID="test-client-id.apps.googleusercontent.com")
    def test_google_sign_in_is_not_blocked_by_it(self):
        self.fail_from_many_addresses(ratelimit.LOGIN_ACCOUNT_LIMIT)
        claims = {
            "iss": "https://accounts.google.com",
            "aud": "test-client-id.apps.googleusercontent.com",
            "sub": "1234567890",
            "email": "alice@example.com",
            "email_verified": True,
            "exp": 9999999999,
        }

        with patch.object(google.google_id_token, "verify_oauth2_token", return_value=claims):
            api = self.client.post(
                "/api/v1/auth/google/",
                {"credential": "x"},
                content_type="application/json",
                REMOTE_ADDR=address(99),
            )
            web = self.client.post(
                "/accounts/google/", {"credential": "x"}, REMOTE_ADDR=address(98)
            )

        self.assertEqual(api.status_code, 200)
        self.assertEqual(web.status_code, 302)
        self.assertEqual(web.url, "/")
