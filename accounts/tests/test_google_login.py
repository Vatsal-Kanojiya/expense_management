"""Sign in with Google (docs/design/GOOGLE_SIGNIN.md): verifying the ID
token and finding or creating the local account (``accounts/google.py``),
and the API endpoint (``auth/google/``) that is the first thing built on it.

The web view and the CSP get their own test classes in this file once a
later commit adds them.

Never calls Google: every test mocks
``google.oauth2.id_token.verify_oauth2_token`` directly, so nothing here
does network I/O.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts import google, ratelimit, totp
from accounts.models import SecurityEvent, TOTPDevice

User = get_user_model()
PASSWORD = "Str0ng-Enough-Pass"

with_cache = override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "google-login-tests",
        }
    }
)

with_google = override_settings(GOOGLE_OAUTH_CLIENT_ID="test-client-id.apps.googleusercontent.com")

# base32("12345678901234567890") -- the RFC 6238 test secret, as in test_mfa.py.
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def code_for(secret, at=None):
    return totp._hotp(secret, totp.current_step(at=at))


def payload(email="alice@example.com", email_verified=True, iss="https://accounts.google.com"):
    return {
        "iss": iss,
        "aud": "test-client-id.apps.googleusercontent.com",
        "sub": "1234567890",
        "email": email,
        "email_verified": email_verified,
        "exp": 9999999999,
    }


def mock_verify(**overrides):
    """Patch the one library call this feature ever makes."""
    return patch.object(google.google_id_token, "verify_oauth2_token", **overrides)


def api_url(name):
    return reverse(f"api:v1:{name}")


# --- Off unless configured -------------------------------------------------


class GoogleSignInOffTests(TestCase):
    def test_google_signin_enabled_is_false_by_default(self):
        self.assertFalse(google.google_signin_enabled())

    @with_google
    def test_google_signin_enabled_is_true_once_configured(self):
        self.assertTrue(google.google_signin_enabled())

    def test_the_api_endpoint_404s_when_unconfigured(self):
        response = self.client.post(api_url("auth-google"), {"credential": "x"})
        self.assertEqual(response.status_code, 404)


# --- accounts/google.py: verification and find-or-create -------------------


@with_google
class VerifyIdTokenTests(TestCase):
    def test_a_good_token_returns_the_lowercased_email(self):
        with mock_verify(return_value=payload(email="Alice@Example.com")):
            self.assertEqual(google.verify_id_token("token"), "alice@example.com")

    def test_email_not_verified_is_refused(self):
        with mock_verify(return_value=payload(email_verified=False)):
            with self.assertRaises(google.GoogleSignInError):
                google.verify_id_token("token")

    def test_bad_issuer_is_refused(self):
        with mock_verify(return_value=payload(iss="https://evil.example.com")):
            with self.assertRaises(google.GoogleSignInError):
                google.verify_id_token("token")

    def test_the_accounts_google_com_issuer_without_scheme_is_accepted(self):
        with mock_verify(return_value=payload(iss="accounts.google.com")):
            self.assertEqual(google.verify_id_token("token"), "alice@example.com")

    def test_a_verifier_error_is_refused_and_the_token_is_never_logged(self):
        with mock_verify(side_effect=ValueError("bad signature: super-secret-token-xyz")):
            with self.assertLogs("accounts.google", level="WARNING") as logs:
                with self.assertRaises(google.GoogleSignInError):
                    google.verify_id_token("super-secret-token-xyz")

        self.assertTrue(logs.output)
        for line in logs.output:
            self.assertNotIn("super-secret-token-xyz", line)

    def test_no_email_in_the_payload_is_refused(self):
        bad = payload()
        del bad["email"]
        with mock_verify(return_value=bad):
            with self.assertRaises(google.GoogleSignInError):
                google.verify_id_token("token")


@with_google
class FindOrCreateUserTests(TestCase):
    def test_an_active_account_is_matched_case_insensitively(self):
        user = User.objects.create_user("alice", "Alice@Example.com", PASSWORD)

        found, created = google.find_or_create_user("alice@example.com")

        self.assertEqual(found.pk, user.pk)
        self.assertFalse(created)

    def test_an_unverified_account_is_activated(self):
        user = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        user.is_active = False
        user.save(update_fields=["is_active"])

        found, created = google.find_or_create_user("alice@example.com")

        found.refresh_from_db()
        self.assertTrue(found.is_active)
        self.assertIsNotNone(found.email_verified_at)
        self.assertFalse(created)

    def test_a_deactivated_verified_account_is_refused(self):
        from django.utils import timezone

        user = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        user.is_active = False
        user.email_verified_at = timezone.now()
        user.save(update_fields=["is_active", "email_verified_at"])

        with self.assertRaises(google.GoogleSignInError):
            google.find_or_create_user("alice@example.com")

    def test_no_match_creates_an_active_user_with_an_unusable_password(self):
        user, created = google.find_or_create_user("newperson@example.com")

        self.assertTrue(created)
        self.assertTrue(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertIsNotNone(user.email_verified_at)
        self.assertEqual(user.username, "newperson")

    def test_a_new_user_gets_the_same_self_participant_as_sign_up(self):
        from expenses.models import Participant

        user, _created = google.find_or_create_user("newperson@example.com")

        self.assertTrue(Participant.objects.filter(user=user, is_self=True).exists())

    def test_username_collisions_get_a_numeric_suffix(self):
        User.objects.create_user("newperson", "someone-else@example.com", PASSWORD)

        user, created = google.find_or_create_user("newperson@example.com")

        self.assertTrue(created)
        self.assertEqual(user.username, "newperson2")

    def test_a_dotted_local_part_becomes_a_clean_username(self):
        user, _created = google.find_or_create_user("first.last+tag@example.com")
        self.assertEqual(user.username, "first.last+tag")


# --- The API endpoint --------------------------------------------------


@with_cache
@with_google
class GoogleLoginApiTests(TestCase):
    def setUp(self):
        cache.clear()

    def post(self, credential="token", **extra):
        return self.client.post(
            api_url("auth-google"),
            {"credential": credential, **extra},
            content_type="application/json",
        )

    def test_a_new_user_is_signed_up_and_signed_in(self):
        with mock_verify(return_value=payload(email="brandnew@example.com")):
            response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
        user = User.objects.get(email="brandnew@example.com")
        self.assertTrue(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertTrue(
            SecurityEvent.objects.filter(
                event="signed_up", user=user, detail={"via": "google"}
            ).exists()
        )
        self.assertTrue(
            SecurityEvent.objects.filter(event="google_login_succeeded", user=user).exists()
        )
        self.assertTrue(SecurityEvent.objects.filter(event="login_succeeded", user=user).exists())

    def test_an_existing_active_user_is_signed_in(self):
        user = User.objects.create_user("alice", "alice@example.com", PASSWORD)

        with mock_verify(return_value=payload()):
            response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["id"], user.pk)
        self.assertFalse(SecurityEvent.objects.filter(event="signed_up", user=user).exists())

    def test_email_not_verified_is_refused(self):
        with mock_verify(return_value=payload(email_verified=False)):
            response = self.post()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "google_failed")
        self.assertTrue(SecurityEvent.objects.filter(event="google_login_failed").exists())

    def test_a_deactivated_verified_account_is_refused(self):
        from django.utils import timezone

        User.objects.create_user(
            "alice",
            "alice@example.com",
            PASSWORD,
            is_active=False,
            email_verified_at=timezone.now(),
        )

        with mock_verify(return_value=payload()):
            response = self.post()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "google_failed")

    def test_verifier_failure_is_refused(self):
        with mock_verify(side_effect=ValueError("boom")):
            response = self.post()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "google_failed")

    def test_an_mfa_user_gets_a_ticket_not_tokens(self):
        user = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        TOTPDevice.objects.create(user=user, secret=RFC_SECRET, confirmed=True)

        with mock_verify(return_value=payload()):
            response = self.post()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["mfa_required"])
        self.assertNotIn("access", data)

        # The ticket works at the usual endpoint.
        verify_response = self.client.post(
            api_url("auth-mfa-verify"),
            {"mfa_ticket": data["mfa_ticket"], "code": code_for(RFC_SECRET)},
            content_type="application/json",
        )
        self.assertEqual(verify_response.status_code, 200)

    @patch.object(ratelimit, "LOGIN_IP_LIMIT", 2)
    def test_rate_limited(self):
        with mock_verify(return_value=payload(email_verified=False)):
            self.post()
            self.post()
            response = self.post()

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["code"], "rate_limited")

    def test_has_password_on_me(self):
        with mock_verify(return_value=payload(email="brandnew@example.com")):
            login_response = self.post()

        me_response = self.client.get(
            api_url("me"), HTTP_AUTHORIZATION=f"Bearer {login_response.json()['access']}"
        )
        self.assertFalse(me_response.json()["has_password"])

    def test_has_password_true_for_a_normal_account(self):
        user = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        with mock_verify(return_value=payload()):
            login_response = self.post()

        me_response = self.client.get(
            api_url("me"), HTTP_AUTHORIZATION=f"Bearer {login_response.json()['access']}"
        )
        self.assertTrue(me_response.json()["has_password"])
        self.assertEqual(me_response.json()["id"], user.pk)
