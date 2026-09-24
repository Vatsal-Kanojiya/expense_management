"""Security pass 1 (commit ea732e4): the protections added, checked one by one."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from rest_framework.throttling import AnonRateThrottle

from accounts import ratelimit


class ClientAddressTests(SimpleTestCase):
    """Which address the limits apply to. Only what a trusted proxy wrote counts."""

    def request(self, forwarded=None):
        extra = {"REMOTE_ADDR": "10.0.0.1"}
        if forwarded is not None:
            extra["HTTP_X_FORWARDED_FOR"] = forwarded
        return RequestFactory().get("/", **extra)

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_without_a_proxy_the_forwarded_header_is_ignored(self):
        self.assertEqual(ratelimit.client_ip(self.request("203.0.113.9")), "10.0.0.1")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_behind_one_proxy_the_right_most_entry_is_used(self):
        request = self.request("198.51.100.7, 203.0.113.9")

        self.assertEqual(ratelimit.client_ip(request), "203.0.113.9")

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_behind_two_proxies_the_second_from_the_right_is_used(self):
        request = self.request("198.51.100.7, 203.0.113.9, 192.0.2.1")

        self.assertEqual(ratelimit.client_ip(request), "203.0.113.9")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_behind_a_proxy_with_no_header_the_socket_address_is_used(self):
        self.assertEqual(ratelimit.client_ip(self.request()), "10.0.0.1")

    def test_the_api_throttle_follows_the_same_rule(self):
        # Default settings: no proxy, so the header must make no difference.
        throttle = AnonRateThrottle()

        first = throttle.get_ident(self.request("203.0.113.9"))
        second = throttle.get_ident(self.request("198.51.100.7"))

        self.assertEqual((first, second), ("10.0.0.1", "10.0.0.1"))


# --- The limits ------------------------------------------------------------

User = get_user_model()
PASSWORD = "Str0ng-Enough-Pass"

with_cache = override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "security-pass1-tests",
        }
    }
)


@with_cache
class LimitTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def setUp(self):
        cache.clear()

    def api(self, path, data, **extra):
        return self.client.post(f"/api/v1/{path}", data, content_type="application/json", **extra)


class SignupLimitTests(LimitTestCase):
    def signup_api(self, n):
        return self.api(
            "auth/signup/",
            {
                "username": f"new{n}",
                "email": f"new{n}@example.com",
                "password": PASSWORD,
                "password_confirm": PASSWORD,
            },
        )

    def signup_web(self, n):
        return self.client.post(
            "/accounts/signup/",
            {
                "username": f"web{n}",
                "email": f"web{n}@example.com",
                "password1": PASSWORD,
                "password2": PASSWORD,
            },
        )

    @patch.object(ratelimit, "SIGNUP_LIMIT", 2)
    def test_the_api_and_the_page_share_one_budget(self):
        self.assertEqual(self.signup_api(1).status_code, 201)
        self.assertEqual(self.signup_web(2).status_code, 302)

        self.assertEqual(self.signup_api(3).status_code, 429)
        self.assertEqual(self.signup_web(4).status_code, 429)
        self.assertEqual(User.objects.filter(username__in=["new3", "web4"]).count(), 0)


class PasswordChangeLimitTests(LimitTestCase):
    def change_api(self, old):
        # Re-read first: after a successful change the stored password hash
        # differs, and Django rightly rejects a session made from a stale copy.
        self.alice.refresh_from_db()
        self.client.force_login(self.alice)
        return self.api(
            "auth/password/change/",
            {
                "old_password": old,
                "new_password": "An0ther-Good-Pass",
                "new_password_confirm": "An0ther-Good-Pass",
            },
        )

    @patch.object(ratelimit, "PASSWORD_CHANGE_LIMIT", 2)
    def test_after_the_limit_even_the_right_password_waits(self):
        self.assertEqual(self.change_api("wrong-1").status_code, 400)
        self.assertEqual(self.change_api("wrong-2").status_code, 400)

        self.assertEqual(self.change_api(PASSWORD).status_code, 429)
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password(PASSWORD))

    @patch.object(ratelimit, "PASSWORD_CHANGE_LIMIT", 2)
    def test_the_page_shares_the_budget(self):
        self.change_api("wrong-1")
        self.change_api("wrong-2")

        response = self.client.post(
            "/accounts/password/change/",
            {
                "old_password": PASSWORD,
                "new_password1": "An0ther-Good-Pass",
                "new_password2": "An0ther-Good-Pass",
            },
        )

        self.assertEqual(response.status_code, 429)

    @patch.object(ratelimit, "PASSWORD_CHANGE_LIMIT", 2)
    def test_a_success_resets_the_count(self):
        self.change_api("wrong-1")
        self.assertEqual(self.change_api(PASSWORD).status_code, 200)

        # The password is now the new one; a wrong guess starts a fresh count.
        self.assertEqual(self.change_api("wrong-again").status_code, 400)


class LoginGuardTests(LimitTestCase):
    """One guard for the web page, the API and the admin site."""

    def api_login(self, username, password):
        return self.api("auth/login/", {"username": username, "password": password})

    def admin_login(self, username, password):
        return self.client.post(
            "/admin/login/",
            {"username": username, "password": password, "next": "/admin/"},
        )

    @patch.object(ratelimit, "LOGIN_LIMIT", 2)
    def test_the_admin_login_is_guarded(self):
        User.objects.create_user("staff", "staff@example.com", PASSWORD, is_staff=True)

        self.assertEqual(self.admin_login("staff", "wrong-1").status_code, 200)
        self.assertEqual(self.admin_login("staff", "wrong-2").status_code, 200)

        self.assertEqual(self.admin_login("staff", PASSWORD).status_code, 429)

    @patch.object(ratelimit, "LOGIN_LIMIT", 2)
    def test_a_good_admin_login_clears_the_count(self):
        User.objects.create_user("staff", "staff@example.com", PASSWORD, is_staff=True)
        self.admin_login("staff", "wrong-1")

        self.assertEqual(self.admin_login("staff", PASSWORD).status_code, 302)
        self.assertFalse(ratelimit.login_blocked(self._request(), "staff"))

    @patch.object(ratelimit, "LOGIN_IP_LIMIT", 3)
    def test_one_address_is_capped_across_usernames(self):
        for name in ("one", "two", "three"):
            self.assertEqual(self.api_login(name, "wrong").status_code, 401)

        # A different username, and the right password: still refused.
        self.assertEqual(self.api_login("alice", PASSWORD).status_code, 429)
        web = self.client.post("/accounts/login/", {"username": "alice", "password": PASSWORD})
        self.assertEqual(web.status_code, 429)

    @patch.object(ratelimit, "LOGIN_IP_LIMIT", 3)
    def test_a_success_clears_only_its_own_username(self):
        self.api_login("alice", "wrong")
        self.api_login("other", "wrong")

        self.assertEqual(self.api_login("alice", PASSWORD).status_code, 200)

        request = self._request()
        self.assertFalse(ratelimit.is_limited("login", request, "alice", 1, 60))
        self.assertTrue(ratelimit.is_limited("login-ip", request, "", 2, 60))

    def test_failed_logins_do_the_same_work_whether_or_not_the_account_exists(self):
        with patch("accounts.api.make_password") as hashing:
            self.api_login("nobody-by-this-name", "wrong")
            self.api_login("alice", "wrong")

        self.assertEqual(hashing.call_count, 2)

    @staticmethod
    def _request():
        # The test client's address, as the limiter sees it.
        return RequestFactory().get("/", REMOTE_ADDR="127.0.0.1")
