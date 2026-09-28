"""Multi-factor sign-in (docs/design/MFA.md): the two-step API -- the login
ticket, ``auth/mfa/verify/``, and the enrolment/disable/regenerate endpoints
under ``auth/mfa/``.
"""

import time as time_module
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework_simplejwt.tokens import RefreshToken

from accounts import mfa, ratelimit, totp
from accounts.models import RecoveryCode, SecurityEvent, TOTPDevice, mfa_enabled

User = get_user_model()
PASSWORD = "Str0ng-Enough-Pass"

with_cache = override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "mfa-tests",
        }
    }
)

# base32("12345678901234567890") -- the RFC 6238 test secret.
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def code_for(secret, at=None):
    return totp._hotp(secret, totp.current_step(at=at))


# --- The API ---------------------------------------------------------------


def api_url(name):
    return reverse(f"api:v1:{name}")


@with_cache
class MFALoginApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def post(self, name, data):
        return self.client.post(api_url(name), data, content_type="application/json")

    def login(self):
        return self.post("auth-login", {"username": "alice", "password": PASSWORD})

    def test_login_without_mfa_is_unchanged(self):
        response = self.login()

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
        self.assertNotIn("mfa_required", response.json())

    def test_login_with_mfa_returns_only_a_ticket(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)

        response = self.login()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body, {"mfa_required": True, "mfa_ticket": body["mfa_ticket"]})
        self.assertNotIn("access", body)
        self.assertFalse(SecurityEvent.objects.filter(event="login_succeeded").exists())

    def test_verify_with_a_totp_code_signs_in(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)
        ticket = self.login().json()["mfa_ticket"]

        response = self.post(
            "auth-mfa-verify", {"mfa_ticket": ticket, "code": code_for(RFC_SECRET)}
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("access", response.json())
        self.assertTrue(SecurityEvent.objects.filter(event="login_succeeded").exists())

    def test_verify_with_a_recovery_code_signs_in_and_cannot_be_reused(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)
        code = RecoveryCode.generate_set(self.user)[0]
        ticket = self.login().json()["mfa_ticket"]

        first = self.post("auth-mfa-verify", {"mfa_ticket": ticket, "code": code})
        self.assertEqual(first.status_code, 200)

        ticket2 = self.login().json()["mfa_ticket"]
        second = self.post("auth-mfa-verify", {"mfa_ticket": ticket2, "code": code})
        self.assertEqual(second.status_code, 400)

    def test_a_wrong_code_is_refused(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)
        ticket = self.login().json()["mfa_ticket"]

        response = self.post("auth-mfa-verify", {"mfa_ticket": ticket, "code": "000000"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("code", response.json())

    def test_an_invalid_ticket_is_refused(self):
        response = self.post("auth-mfa-verify", {"mfa_ticket": "garbage", "code": "000000"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_ticket")

    def test_an_expired_ticket_is_refused(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)
        with patch.object(
            signing.TimestampSigner,
            "timestamp",
            lambda self: signing.b62_encode(int(time_module.time() - mfa.TICKET_MAX_AGE - 5)),
        ):
            ticket = mfa.make_ticket(self.user)

        response = self.post(
            "auth-mfa-verify", {"mfa_ticket": ticket, "code": code_for(RFC_SECRET)}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_ticket")

    def test_a_ticket_from_before_a_password_change_is_refused(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)
        ticket = self.login().json()["mfa_ticket"]

        self.user.set_password("Another-Good-Pass1")
        self.user.save()

        response = self.post(
            "auth-mfa-verify", {"mfa_ticket": ticket, "code": code_for(RFC_SECRET)}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_ticket")

    @patch.object(ratelimit, "MFA_LIMIT", 2)
    def test_the_per_account_attempt_limit(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)
        ticket = self.login().json()["mfa_ticket"]

        self.post("auth-mfa-verify", {"mfa_ticket": ticket, "code": "000000"})
        self.post("auth-mfa-verify", {"mfa_ticket": ticket, "code": "000000"})

        response = self.post(
            "auth-mfa-verify", {"mfa_ticket": ticket, "code": code_for(RFC_SECRET)}
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["code"], "rate_limited")


@with_cache
class MFAManageApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def post(self, name, data=None, auth=True):
        extra = self.bearer() if auth else {}
        return self.client.post(api_url(name), data or {}, content_type="application/json", **extra)

    def get(self, name, auth=True):
        extra = self.bearer() if auth else {}
        return self.client.get(api_url(name), **extra)

    def bearer(self):
        # Minted directly, not through /auth/login/ -- several tests here
        # set the account up with MFA already on, which would turn a
        # password login into a ticket instead of a token pair.
        access = str(RefreshToken.for_user(self.user).access_token)
        return {"HTTP_AUTHORIZATION": f"Bearer {access}"}

    def test_status_when_off(self):
        response = self.get("auth-mfa-status")
        self.assertEqual(response.json(), {"enabled": False, "recovery_codes_left": 0})

    def test_setup_returns_a_secret_and_uri(self):
        response = self.post("auth-mfa-setup")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["secret"]), 32)
        self.assertIn(body["secret"], body["otpauth_uri"])
        self.assertTrue(TOTPDevice.objects.filter(user=self.user, confirmed=False).exists())

    def test_setup_again_replaces_the_pending_device(self):
        first = self.post("auth-mfa-setup").json()["secret"]
        second = self.post("auth-mfa-setup").json()["secret"]

        self.assertNotEqual(first, second)
        self.assertEqual(TOTPDevice.objects.filter(user=self.user).count(), 1)

    def test_setup_is_refused_once_already_enabled(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)

        response = self.post("auth-mfa-setup")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "mfa_already_enabled")

    def test_confirm_with_the_right_code_turns_it_on(self):
        secret = self.post("auth-mfa-setup").json()["secret"]

        response = self.post("auth-mfa-confirm", {"code": code_for(secret)})

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(len(body["recovery_codes"]), 10)
        self.assertIn("access", body)
        self.assertTrue(mfa_enabled(self.user))
        self.assertTrue(SecurityEvent.objects.filter(event="mfa_enabled").exists())

    def test_confirm_revokes_other_refresh_tokens(self):
        other_refresh = self.client.post(
            api_url("auth-login"),
            {"username": "alice", "password": PASSWORD},
            content_type="application/json",
        ).json()["refresh"]
        secret = self.post("auth-mfa-setup").json()["secret"]

        self.post("auth-mfa-confirm", {"code": code_for(secret)})

        refresh_attempt = self.client.post(
            api_url("auth-refresh"), {"refresh": other_refresh}, content_type="application/json"
        )
        self.assertEqual(refresh_attempt.status_code, 401)

    def test_confirm_with_a_wrong_code_is_refused(self):
        self.post("auth-mfa-setup")

        response = self.post("auth-mfa-confirm", {"code": "000000"})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(mfa_enabled(self.user))

    def test_confirm_with_nothing_pending_is_refused(self):
        response = self.post("auth-mfa-confirm", {"code": "000000"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "mfa_setup_not_started")

    def test_status_when_on(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)
        RecoveryCode.generate_set(self.user)

        response = self.get("auth-mfa-status")

        self.assertEqual(response.json(), {"enabled": True, "recovery_codes_left": 10})

    def test_disable_needs_the_right_password_and_code(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)
        RecoveryCode.generate_set(self.user)

        response = self.post(
            "auth-mfa-disable", {"password": PASSWORD, "code": code_for(RFC_SECRET)}
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(mfa_enabled(self.user))
        self.assertFalse(RecoveryCode.objects.filter(user=self.user).exists())
        self.assertTrue(SecurityEvent.objects.filter(event="mfa_disabled").exists())

    def test_disable_with_the_wrong_password_is_refused(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)

        response = self.post(
            "auth-mfa-disable", {"password": "wrong-password", "code": code_for(RFC_SECRET)}
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(mfa_enabled(self.user))

    def test_disable_with_the_wrong_code_is_refused(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)

        response = self.post("auth-mfa-disable", {"password": PASSWORD, "code": "000000"})

        self.assertEqual(response.status_code, 400)
        self.assertTrue(mfa_enabled(self.user))

    def test_disable_accepts_a_recovery_code_too(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)
        code = RecoveryCode.generate_set(self.user)[0]

        response = self.post("auth-mfa-disable", {"password": PASSWORD, "code": code})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(mfa_enabled(self.user))

    def test_disable_when_not_enabled_is_refused(self):
        response = self.post("auth-mfa-disable", {"password": PASSWORD, "code": "000000"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "mfa_not_enabled")

    def test_regenerate_recovery_codes(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)
        old = RecoveryCode.generate_set(self.user)

        response = self.post("auth-mfa-recovery-codes", {"code": code_for(RFC_SECRET)})

        self.assertEqual(response.status_code, 200)
        new = response.json()["recovery_codes"]
        self.assertEqual(len(new), 10)
        self.assertFalse(set(old) & set(new))
        self.assertTrue(SecurityEvent.objects.filter(event="recovery_codes_regenerated").exists())

    def test_regenerate_does_not_accept_a_recovery_code(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)
        code = RecoveryCode.generate_set(self.user)[0]

        response = self.post("auth-mfa-recovery-codes", {"code": code})

        self.assertEqual(response.status_code, 400)

    def test_regenerate_when_not_enabled_is_refused(self):
        response = self.post("auth-mfa-recovery-codes", {"code": "000000"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "mfa_not_enabled")
