"""Sign in with Google (docs/design/GOOGLE_SIGNIN.md): verifying the ID
token and finding or creating the local account (``accounts/google.py``).

The API endpoint, the web view and the CSP get their own test classes in
this file as later commits add them.

Never calls Google: every test mocks
``google.oauth2.id_token.verify_oauth2_token`` directly, so nothing here
does network I/O.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from accounts import google

User = get_user_model()
PASSWORD = "Str0ng-Enough-Pass"

with_google = override_settings(GOOGLE_OAUTH_CLIENT_ID="test-client-id.apps.googleusercontent.com")


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


# --- Off unless configured -------------------------------------------------


class GoogleSignInOffTests(TestCase):
    def test_google_signin_enabled_is_false_by_default(self):
        self.assertFalse(google.google_signin_enabled())

    @with_google
    def test_google_signin_enabled_is_true_once_configured(self):
        self.assertTrue(google.google_signin_enabled())


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
