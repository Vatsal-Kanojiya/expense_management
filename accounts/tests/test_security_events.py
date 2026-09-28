"""Roadmap A3: the security event trail (accounts.SecurityEvent, accounts/audit.py).

Each event is recorded exactly once on its own path -- web, API or admin
-- and never carries anything secret. A cache-backed rate limiter is
needed for the *_blocked cases, so those use ``with_cache`` like the
rate-limit tests do (accounts/tests/test_security_pass1.py).
"""

import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts import audit, ratelimit
from accounts.models import SecurityEvent

User = get_user_model()
PASSWORD = "Str0ng-Enough-Pass"

with_cache = override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "security-events-tests",
        }
    }
)


def api(path, data):
    from django.test import Client

    return Client().post(f"/api/v1/{path}", data, content_type="application/json")


def events(event):
    return SecurityEvent.objects.filter(event=event)


@with_cache
class WebLoginEventTests(TestCase):
    # Class-level, not per-method: an override_settings applied only to a
    # test method does not cover setUp(), so a per-method cache.clear()
    # would clear the *default* (dummy) cache and leave the real one --
    # shared by every class below that also opts into it -- dirty for the
    # next test that uses it.
    def setUp(self):
        cache.clear()

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def test_a_successful_login_is_recorded_once(self):
        self.client.post(reverse("accounts:login"), {"username": "alice", "password": PASSWORD})

        rows = events("login_succeeded")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().user, self.alice)

    def test_a_failed_login_is_recorded_once(self):
        self.client.post(reverse("accounts:login"), {"username": "alice", "password": "wrong"})

        rows = events("login_failed")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().username, "alice")

    @mock.patch.object(ratelimit, "LOGIN_LIMIT", 1)
    def test_a_blocked_login_is_recorded(self):
        self.client.post(reverse("accounts:login"), {"username": "alice", "password": "wrong"})
        self.client.post(reverse("accounts:login"), {"username": "alice", "password": "wrong"})

        self.assertEqual(events("login_blocked").count(), 1)

    def test_logout_is_recorded(self):
        self.client.force_login(self.alice)

        self.client.post(reverse("accounts:logout"))

        rows = events("logged_out")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().user, self.alice)


@with_cache
class AdminLoginEventTests(TestCase):
    """docs/design/MFA.md: the admin's own login form no longer checks
    credentials at all, so it records nothing -- whatever happens at
    /accounts/login/, which it redirects to, is what gets recorded there.
    """

    def setUp(self):
        cache.clear()

    def test_the_admin_login_itself_records_nothing(self):
        User.objects.create_user("staff", "staff@example.com", PASSWORD, is_staff=True)

        self.client.post("/admin/login/", {"username": "staff", "password": PASSWORD})

        self.assertEqual(SecurityEvent.objects.count(), 0)

    def test_signing_in_at_the_site_login_the_admin_redirects_to_is_recorded(self):
        User.objects.create_user("staff", "staff@example.com", PASSWORD, is_staff=True)

        self.client.post(
            "/accounts/login/?next=/admin/", {"username": "staff", "password": PASSWORD}
        )

        self.assertEqual(events("login_succeeded").count(), 1)


@with_cache
class ApiLoginEventTests(TestCase):
    def setUp(self):
        cache.clear()

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def test_a_successful_login_is_recorded_once(self):
        api("auth/login/", {"username": "alice", "password": PASSWORD})

        self.assertEqual(events("login_succeeded").count(), 1)
        # And never twice: the API login never calls django's login(), so
        # the user_logged_in signal (accounts/signals.py) never also fires.
        self.assertEqual(SecurityEvent.objects.filter(user=self.alice).count(), 1)

    def test_a_failed_login_is_recorded_once(self):
        api("auth/login/", {"username": "alice", "password": "wrong"})

        self.assertEqual(events("login_failed").count(), 1)

    @mock.patch.object(ratelimit, "LOGIN_LIMIT", 1)
    def test_a_blocked_login_is_recorded(self):
        api("auth/login/", {"username": "alice", "password": "wrong"})
        api("auth/login/", {"username": "alice", "password": "wrong"})

        self.assertEqual(events("login_blocked").count(), 1)

    def test_logout_is_recorded_with_the_token_holders_identity(self):
        login = api("auth/login/", {"username": "alice", "password": PASSWORD}).json()

        api("auth/logout/", {"refresh": login["refresh"]})

        rows = events("logged_out")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().user, self.alice)


class SignupAndVerificationEventTests(TestCase):
    def test_web_signup_is_recorded(self):
        self.client.post(
            reverse("accounts:signup"),
            {
                "username": "bella",
                "email": "bella@example.com",
                "password1": PASSWORD,
                "password2": PASSWORD,
            },
        )

        self.assertEqual(events("signed_up").count(), 1)

    def test_web_email_verified_is_recorded(self):
        self.client.post(
            reverse("accounts:signup"),
            {
                "username": "bella",
                "email": "bella@example.com",
                "password1": PASSWORD,
                "password2": PASSWORD,
            },
        )
        link = re.search(r"(/accounts/verify/[^/\s]+/[^/\s]+/)", mail.outbox[0].body).group(1)

        self.client.get(link)

        self.assertEqual(events("email_verified").count(), 1)

    def test_api_signup_is_recorded(self):
        api(
            "auth/signup/",
            {
                "username": "carla",
                "email": "carla@example.com",
                "password": PASSWORD,
                "password_confirm": PASSWORD,
            },
        )

        self.assertEqual(events("signed_up").count(), 1)

    # The API mails the frontend's /verify-email/ link only when a frontend
    # is configured; without this the test depended on a local .env.
    @override_settings(FRONTEND_URL="http://frontend.test")
    def test_api_email_verified_is_recorded(self):
        api(
            "auth/signup/",
            {
                "username": "carla",
                "email": "carla@example.com",
                "password": PASSWORD,
                "password_confirm": PASSWORD,
            },
        )
        match = re.search(r"/verify-email/([^/\s]+)/([^/\s]+)", mail.outbox[0].body)

        api("auth/verify-email/", {"uid": match.group(1), "token": match.group(2)})

        self.assertEqual(events("email_verified").count(), 1)


class PasswordEventTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def setUp(self):
        cache.clear()

    def test_web_password_change_records_changed_and_revoked(self):
        self.client.force_login(self.alice)

        self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": PASSWORD,
                "new_password1": "a-New-Str0nger-1",
                "new_password2": "a-New-Str0nger-1",
            },
        )

        self.assertEqual(events("password_changed").count(), 1)
        self.assertEqual(events("tokens_revoked").count(), 1)

    def test_api_password_change_records_changed_and_revoked(self):
        login = api("auth/login/", {"username": "alice", "password": PASSWORD}).json()

        from django.test import Client

        client = Client()
        client.post(
            "/api/v1/auth/password/change/",
            {
                "old_password": PASSWORD,
                "new_password": "a-New-Str0nger-1",
                "new_password_confirm": "a-New-Str0nger-1",
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {login['access']}",
        )

        self.assertEqual(events("password_changed").count(), 1)
        self.assertEqual(events("tokens_revoked").count(), 1)

    def test_web_password_reset_request_is_recorded_even_for_an_unknown_email(self):
        self.client.post(reverse("accounts:password_reset"), {"email": "nobody@example.com"})

        rows = events("password_reset_requested")
        self.assertEqual(rows.count(), 1)
        self.assertIsNone(rows.first().user)
        self.assertEqual(rows.first().detail.get("email"), "nobody@example.com")

    def test_web_password_reset_completion_is_recorded(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        uidb64 = urlsafe_base64_encode(force_bytes(self.alice.pk))
        token = default_token_generator.make_token(self.alice)

        link = reverse("accounts:password_reset_confirm", kwargs={"uidb64": uidb64, "token": token})
        response = self.client.get(link, follow=True)
        confirm_url = response.redirect_chain[-1][0]

        self.client.post(
            confirm_url,
            {"new_password1": "a-New-Str0nger-1", "new_password2": "a-New-Str0nger-1"},
        )

        self.assertEqual(events("password_reset_completed").count(), 1)
        self.assertEqual(events("tokens_revoked").count(), 1)

    def test_api_password_reset_completion_is_recorded(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        uid = urlsafe_base64_encode(force_bytes(self.alice.pk))
        token = default_token_generator.make_token(self.alice)

        api(
            "auth/password/reset/confirm/",
            {
                "uid": uid,
                "token": token,
                "new_password": "a-New-Str0nger-1",
                "new_password_confirm": "a-New-Str0nger-1",
            },
        )

        self.assertEqual(events("password_reset_completed").count(), 1)
        self.assertEqual(events("tokens_revoked").count(), 1)


class NoSecretsInDetailTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_a_failed_login_never_stores_the_password(self):
        User.objects.create_user("alice", "alice@example.com", PASSWORD)

        self.client.post(
            reverse("accounts:login"), {"username": "alice", "password": "super-secret-guess"}
        )

        for row in SecurityEvent.objects.all():
            self.assertNotIn("super-secret-guess", str(row.detail))

    def test_tokens_revoked_carries_no_token_value(self):
        alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        audit.record("tokens_revoked", user=alice)

        row = events("tokens_revoked").first()
        self.assertEqual(row.detail, {})


class RecordNeverRaisesTests(TestCase):
    def test_a_failure_inside_record_does_not_break_the_login(self):
        User.objects.create_user("alice", "alice@example.com", PASSWORD)

        with mock.patch(
            "accounts.audit.SecurityEvent.objects.create", side_effect=RuntimeError("boom")
        ):
            response = self.client.post(
                reverse("accounts:login"), {"username": "alice", "password": PASSWORD}
            )

        self.assertRedirects(response, reverse("expenses:dashboard"))
        self.assertEqual(SecurityEvent.objects.count(), 0)


class AccountDeletionEventTests(TestCase):
    def test_deletion_records_account_deleted_and_blanks_earlier_usernames(self):
        alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        audit.record("password_changed", user=alice, username="alice")

        self.client.force_login(alice)
        self.client.post(reverse("accounts:delete_account"), {"confirm": "alice"})

        rows = SecurityEvent.objects.all()
        self.assertGreaterEqual(rows.count(), 2)
        for row in rows:
            self.assertEqual(row.username, "")
            self.assertIsNone(row.user)

        deletion = SecurityEvent.objects.get(event="account_deleted")
        self.assertEqual(deletion.detail.get("user_id"), alice.pk)


class PurgeSecurityEventsCommandTests(TestCase):
    def test_retention_purge_removes_only_old_rows(self):
        from django.core.management import call_command
        from django.utils import timezone

        old = SecurityEvent.objects.create(event="login_succeeded", username="old")
        SecurityEvent.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=400)
        )
        recent = SecurityEvent.objects.create(event="login_succeeded", username="recent")

        call_command("purge_security_events", days=365)

        self.assertFalse(SecurityEvent.objects.filter(pk=old.pk).exists())
        self.assertTrue(SecurityEvent.objects.filter(pk=recent.pk).exists())

    def test_dry_run_removes_nothing(self):
        from django.core.management import call_command
        from django.utils import timezone

        old = SecurityEvent.objects.create(event="login_succeeded", username="old")
        SecurityEvent.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=400)
        )

        call_command("purge_security_events", days=365, dry_run=True)

        self.assertTrue(SecurityEvent.objects.filter(pk=old.pk).exists())


class EventAddressTests(TestCase):
    """The address column only ever gets a real IP address.

    On Postgres it is an IP type, and a value like "unknown" made the whole
    event fail to save.
    """

    def test_a_request_without_an_address_still_records_the_event(self):
        from django.test import RequestFactory

        from accounts import audit
        from accounts.models import SecurityEvent

        request = RequestFactory().get("/")
        del request.META["REMOTE_ADDR"]

        audit.record("login_failed", request=request, username="nobody")

        event = SecurityEvent.objects.get(event="login_failed", username="nobody")
        self.assertIsNone(event.ip)

    def test_a_real_address_is_kept(self):
        from django.test import RequestFactory

        from accounts import audit
        from accounts.models import SecurityEvent

        audit.record(
            "login_failed",
            request=RequestFactory().get("/", REMOTE_ADDR="203.0.113.7"),
            username="x",
        )

        self.assertEqual(SecurityEvent.objects.get(username="x").ip, "203.0.113.7")
