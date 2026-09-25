"""Security pass 4 (HANDOVER.md): tokens, sessions and headers.

Each checklist item is its own section below, in the order HANDOVER.md
lists them. Commits land one section at a time. Several items were already
correctly implemented; those sections pin the existing behaviour rather
than changing it, and say so.
"""

import json
import os
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()
PASSWORD = "Str0ng-Enough-Pass"
BASE_DIR = Path(__file__).resolve().parent.parent.parent


def api_url(name):
    return reverse(f"api:v1:{name}")


# --- Item 1: API token lifetimes, logout, rotation -------------------------


class TokenSettingsTests(SimpleTestCase):
    """SIMPLE_JWT (config/settings.py) was already correct. Pin the values."""

    def test_access_tokens_are_short_lived(self):
        self.assertEqual(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"], timedelta(minutes=30))

    def test_refresh_tokens_are_bounded(self):
        self.assertEqual(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"], timedelta(days=14))

    def test_refresh_tokens_rotate_and_the_old_one_is_blacklisted(self):
        self.assertTrue(settings.SIMPLE_JWT["ROTATE_REFRESH_TOKENS"])
        self.assertTrue(settings.SIMPLE_JWT["BLACKLIST_AFTER_ROTATION"])

    def test_access_tokens_are_tied_to_the_password_hash(self):
        # What makes a password change end already-issued access tokens
        # without a blacklist entry for each one -- see
        # accounts/api.py's revoke_refresh_tokens docstring.
        self.assertTrue(settings.SIMPLE_JWT["CHECK_REVOKE_TOKEN"])

    def test_the_blacklist_app_is_installed(self):
        # Without it, logout and rotation have nowhere to record a
        # revoked token, and both become no-ops.
        self.assertIn("rest_framework_simplejwt.token_blacklist", settings.INSTALLED_APPS)


class RefreshTokenBlacklistRecordTests(TestCase):
    """Logout and rotation leave a real row behind, not just a 401 later."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def test_logout_records_a_blacklist_entry_for_that_token(self):
        refresh = RefreshToken.for_user(self.alice)
        outstanding = OutstandingToken.objects.get(jti=refresh["jti"])
        self.assertFalse(BlacklistedToken.objects.filter(token=outstanding).exists())

        response = self.client.post(
            api_url("auth-logout"), {"refresh": str(refresh)}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 204)
        self.assertTrue(BlacklistedToken.objects.filter(token=outstanding).exists())

    def test_rotation_blacklists_the_token_it_replaces(self):
        refresh = RefreshToken.for_user(self.alice)
        outstanding = OutstandingToken.objects.get(jti=refresh["jti"])

        response = self.client.post(
            api_url("auth-refresh"), {"refresh": str(refresh)}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(BlacklistedToken.objects.filter(token=outstanding).exists())
        # And the new one issued in its place is not itself blacklisted.
        new_token = RefreshToken(response.json()["refresh"])
        new_outstanding = OutstandingToken.objects.get(jti=new_token["jti"])
        self.assertFalse(BlacklistedToken.objects.filter(token=new_outstanding).exists())


# --- Item 2: password change/reset end other sign-ins -----------------------


class WebPasswordChangeRevokesRefreshTokensTests(TestCase):
    """Gap: accounts/views.py's ThrottledPasswordChangeView did not call
    revoke_refresh_tokens, so a refresh token issued to a mobile/SPA client
    survived a password change made through the Django page. Fixed by
    calling it from form_valid, the same way accounts/api.py's
    PasswordChangeView already did for a change made through the API.
    """

    def setUp(self):
        self.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def refresh(self, token):
        return self.client.post(
            api_url("auth-refresh"), {"refresh": str(token)}, content_type="application/json"
        )

    def test_changing_the_password_on_the_web_page_blacklists_refresh_tokens(self):
        token = RefreshToken.for_user(self.alice)
        self.assertEqual(self.refresh(token).status_code, 200)
        token = RefreshToken.for_user(self.alice)  # a second, still-live token

        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": PASSWORD,
                "new_password1": "An0ther-Good-Pass",
                "new_password2": "An0ther-Good-Pass",
            },
        )

        self.assertRedirects(response, reverse("accounts:password_change_done"))
        self.assertEqual(self.refresh(token).status_code, 401)

    def test_a_failed_change_does_not_revoke_anything(self):
        token = RefreshToken.for_user(self.alice)

        self.client.force_login(self.alice)
        self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": "wrong-password",
                "new_password1": "An0ther-Good-Pass",
                "new_password2": "An0ther-Good-Pass",
            },
        )

        self.assertEqual(self.refresh(token).status_code, 200)


class WebPasswordResetRevokesRefreshTokensTests(TestCase):
    """Same gap, in ``PasswordResetConfirmView``: fixed by
    ThrottledPasswordResetConfirmView (accounts/views.py, accounts/urls.py).
    """

    def setUp(self):
        self.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def refresh(self, token):
        return self.client.post(
            api_url("auth-refresh"), {"refresh": str(token)}, content_type="application/json"
        )

    def _reset_link(self):
        mail.outbox = []
        self.client.post(reverse("accounts:password_reset"), {"email": "alice@example.com"})
        return re.search(r"(/accounts/password/reset/[^/\s]+/[^/\s]+/)", mail.outbox[0].body).group(
            1
        )

    def test_confirming_a_reset_on_the_web_page_blacklists_refresh_tokens(self):
        token = RefreshToken.for_user(self.alice)
        link = self._reset_link()
        final_url = self.client.get(link, follow=True).redirect_chain[-1][0]

        response = self.client.post(
            final_url,
            {"new_password1": "An0ther-Good-Pass", "new_password2": "An0ther-Good-Pass"},
        )

        self.assertRedirects(response, reverse("accounts:password_reset_complete"))
        self.assertEqual(self.refresh(token).status_code, 401)


# --- Item 3: cookies and sessions -------------------------------------------


def _production_settings(**overrides):
    """The values config/settings.py computes under ``if not DEBUG``.

    override_settings cannot help here: that block has already run by the
    time any test executes, so the only honest way to read the production
    configuration is a fresh process with DEBUG unset -- the same
    constraint expenses/tests/test_error_pages.py's DeploySettingsTests
    documents for `check --deploy` itself.
    """
    env = {**os.environ, "DEBUG": "False", "ALLOWED_HOSTS": "example.com"}
    # compose.yaml turns these off for local HTTP (DECISIONS D35) and
    # `make test`/CI inherit that; popped so this measures the production
    # configuration, not the relaxed local one.
    for relaxed in ("SECURE_SSL_REDIRECT", "SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE"):
        env.pop(relaxed, None)
    env.update(overrides)

    fields = [
        "SESSION_COOKIE_SECURE",
        "CSRF_COOKIE_SECURE",
        "SESSION_COOKIE_HTTPONLY",
        "CSRF_COOKIE_HTTPONLY",
        "SESSION_COOKIE_SAMESITE",
        "CSRF_COOKIE_SAMESITE",
        "SESSION_COOKIE_AGE",
        "SECURE_HSTS_SECONDS",
        "SECURE_HSTS_INCLUDE_SUBDOMAINS",
        "SECURE_REFERRER_POLICY",
        "X_FRAME_OPTIONS",
        "SECURE_CONTENT_TYPE_NOSNIFF",
    ]
    script = (
        "import django, os, json;"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings');"
        "django.setup();"
        "from django.conf import settings;"
        f"print(json.dumps({{f: getattr(settings, f) for f in {fields!r}}}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=BASE_DIR, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


class ProductionCookieAndHeaderSettingsTests(SimpleTestCase):
    """SESSION_COOKIE_*/CSRF_COOKIE_*/SECURE_* were already correct. Pin them."""

    def test_cookies_are_secure_httponly_and_samesite_in_production(self):
        values = _production_settings()

        self.assertTrue(values["SESSION_COOKIE_SECURE"])
        self.assertTrue(values["CSRF_COOKIE_SECURE"])
        self.assertTrue(values["SESSION_COOKIE_HTTPONLY"])
        # Deliberately False -- config/settings.py's comment: it would
        # break any future JS that has to read the token for an AJAX POST.
        self.assertFalse(values["CSRF_COOKIE_HTTPONLY"])
        self.assertEqual(values["SESSION_COOKIE_SAMESITE"], "Lax")
        self.assertEqual(values["CSRF_COOKIE_SAMESITE"], "Lax")

    def test_sessions_are_bounded(self):
        # Django's own default (two weeks). Nothing overrides it, which is
        # the point: a session expires rather than lasting forever.
        self.assertEqual(_production_settings()["SESSION_COOKIE_AGE"], 1209600)

    def test_hsts_referrer_policy_and_frame_options_are_set(self):
        values = _production_settings()

        self.assertGreater(values["SECURE_HSTS_SECONDS"], 0)
        self.assertTrue(values["SECURE_HSTS_INCLUDE_SUBDOMAINS"])
        self.assertEqual(values["SECURE_REFERRER_POLICY"], "same-origin")
        self.assertEqual(values["X_FRAME_OPTIONS"], "DENY")
        self.assertTrue(values["SECURE_CONTENT_TYPE_NOSNIFF"])

    def test_local_http_keeps_httponly_and_samesite_even_with_secure_off(self):
        # D35: only the Secure switches move for local HTTP (compose.yaml).
        # Everything else in this section stays at its secure default.
        values = _production_settings(SESSION_COOKIE_SECURE="False", CSRF_COOKIE_SECURE="False")

        self.assertFalse(values["SESSION_COOKIE_SECURE"])
        self.assertFalse(values["CSRF_COOKIE_SECURE"])
        self.assertTrue(values["SESSION_COOKIE_HTTPONLY"])
        self.assertEqual(values["SESSION_COOKIE_SAMESITE"], "Lax")


class SessionIdRotatesAtLoginTests(TestCase):
    def test_the_session_key_changes_after_a_successful_login(self):
        User.objects.create_user("alice", "alice@example.com", PASSWORD)

        # An anonymous session that already holds a key, the way a cart or
        # a "remember this device" flag would before the person signs in.
        session = self.client.session
        session["pre_login_marker"] = True
        session.save()
        old_key = session.session_key
        self.assertIsNotNone(old_key)

        self.client.post(reverse("accounts:login"), {"username": "alice", "password": PASSWORD})

        new_key = self.client.session.session_key
        self.assertIsNotNone(new_key)
        self.assertNotEqual(old_key, new_key)
