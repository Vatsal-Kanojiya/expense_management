"""Review of multi-factor sign-in: changing its settings is limited too.

Disabling two-step sign-in and minting recovery codes are reached with a
signed-in session. Without a limit, whoever holds one could guess the
password and then the six-digit code until two-step sign-in was off.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework_simplejwt.tokens import RefreshToken

from accounts import mfa, ratelimit, totp
from accounts.models import TOTPDevice, mfa_enabled

User = get_user_model()
PASSWORD = "Str0ng-Enough-Pass"
SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def current_code():
    return totp._hotp(SECRET, totp.current_step())


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class ChangingMfaIsLimitedTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        TOTPDevice.objects.create(user=self.user, secret=SECRET, confirmed=True)

    def api(self, name, data):
        access = str(RefreshToken.for_user(self.user).access_token)
        return self.client.post(
            reverse(f"api:v1:{name}"),
            data,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )

    @patch.object(ratelimit, "PASSWORD_CHANGE_LIMIT", 2)
    def test_disable_counts_wrong_passwords(self):
        for guess in ("wrong-1", "wrong-2"):
            self.assertEqual(
                self.api("auth-mfa-disable", {"password": guess, "code": "000000"}).status_code,
                400,
            )

        refused = self.api("auth-mfa-disable", {"password": PASSWORD, "code": current_code()})

        self.assertEqual(refused.status_code, 429)
        self.assertTrue(mfa_enabled(self.user))

    @patch.object(ratelimit, "MFA_LIMIT", 2)
    def test_disable_counts_wrong_codes(self):
        for guess in ("111111", "222222"):
            self.assertEqual(
                self.api("auth-mfa-disable", {"password": PASSWORD, "code": guess}).status_code,
                400,
            )

        refused = self.api("auth-mfa-disable", {"password": PASSWORD, "code": current_code()})

        self.assertEqual(refused.status_code, 429)
        self.assertTrue(mfa_enabled(self.user))

    @patch.object(ratelimit, "MFA_LIMIT", 2)
    def test_new_recovery_codes_count_wrong_codes(self):
        for guess in ("111111", "222222"):
            self.api("auth-mfa-recovery-codes", {"code": guess})

        refused = self.api("auth-mfa-recovery-codes", {"code": current_code()})

        self.assertEqual(refused.status_code, 429)

    @patch.object(ratelimit, "MFA_LIMIT", 2)
    def test_the_web_page_shares_the_budget(self):
        self.api("auth-mfa-disable", {"password": PASSWORD, "code": "111111"})
        self.api("auth-mfa-disable", {"password": PASSWORD, "code": "222222"})
        self.client.force_login(self.user)

        self.client.post(
            reverse("accounts:mfa_disable"), {"password": PASSWORD, "code": current_code()}
        )

        self.assertTrue(mfa_enabled(self.user))

    def test_a_right_password_and_code_still_turn_it_off(self):
        response = self.api("auth-mfa-disable", {"password": PASSWORD, "code": current_code()})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(mfa_enabled(self.user))


class TicketForDeactivatedAccountTests(TestCase):
    def test_a_ticket_stops_working_when_the_account_is_switched_off(self):
        user = User.objects.create_user("bob", "bob@example.com", PASSWORD)
        ticket = mfa.make_ticket(user)
        User.objects.filter(pk=user.pk).update(is_active=False)

        self.assertIsNone(mfa.user_for_ticket(ticket, User))
