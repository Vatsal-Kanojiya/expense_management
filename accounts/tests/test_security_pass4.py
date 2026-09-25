"""Security pass 4 (HANDOVER.md): tokens, sessions and headers.

Each checklist item is its own section below, in the order HANDOVER.md
lists them. Commits land one section at a time. Several items were already
correctly implemented; those sections pin the existing behaviour rather
than changing it, and say so.
"""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()
PASSWORD = "Str0ng-Enough-Pass"


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
