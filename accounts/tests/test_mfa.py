"""Multi-factor sign-in (docs/design/MFA.md): the TOTP math (accounts/totp.py),
the TOTPDevice and RecoveryCode models, the mfa_enabled() helper, and the
signed ticket and shared verify_code() logic (accounts/mfa.py) that the API
and the web pages both build on.
"""

import time as time_module
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

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


# --- TOTP (accounts/totp.py), against the RFC 6238 test vectors ----------


class TOTPTests(TestCase):
    def test_rfc6238_test_vectors(self):
        # The RFC's own vectors are 8-digit HOTP codes; the rightmost 6
        # digits are exactly what a 6-digit truncation gives for the same
        # counter, since X mod 10**6 == (X mod 10**8) mod 10**6.
        vectors = [
            (59, "287082"),
            (1111111109, "081804"),
            (1111111111, "050471"),
            (1234567890, "005924"),
            (2000000000, "279037"),
            (20000000000, "353130"),
        ]
        for at, expected in vectors:
            with self.subTest(at=at):
                step = totp.current_step(at=at)
                self.assertEqual(totp.verify(RFC_SECRET, expected, 0, at=at), step)

    def test_one_step_either_side_is_accepted(self):
        at = 1_700_000_000
        step = totp.current_step(at=at)

        self.assertEqual(
            totp.verify(RFC_SECRET, totp._hotp(RFC_SECRET, step - 1), 0, at=at), step - 1
        )
        self.assertEqual(
            totp.verify(RFC_SECRET, totp._hotp(RFC_SECRET, step + 1), 0, at=at), step + 1
        )

    def test_two_steps_away_is_refused(self):
        at = 1_700_000_000
        step = totp.current_step(at=at)

        self.assertIsNone(totp.verify(RFC_SECRET, totp._hotp(RFC_SECRET, step + 2), 0, at=at))

    def test_a_step_at_or_before_last_used_is_refused(self):
        at = 1_700_000_000
        step = totp.current_step(at=at)
        code = totp._hotp(RFC_SECRET, step)

        self.assertIsNone(totp.verify(RFC_SECRET, code, last_used_step=step, at=at))
        self.assertIsNone(totp.verify(RFC_SECRET, code, last_used_step=step + 1, at=at))

    def test_garbage_codes_are_refused(self):
        self.assertIsNone(totp.verify(RFC_SECRET, "", 0, at=1000))
        self.assertIsNone(totp.verify(RFC_SECRET, "abcdef", 0, at=1000))
        self.assertIsNone(totp.verify(RFC_SECRET, "12345", 0, at=1000))  # too short

    def test_generate_secret_is_32_base32_characters(self):
        secret = totp.generate_secret()
        self.assertEqual(len(secret), 32)
        self.assertTrue(set(secret) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"))

    def test_otpauth_uri_names_the_account_and_issuer(self):
        uri = totp.otpauth_uri(RFC_SECRET, "alice", issuer="Test Co")

        self.assertTrue(uri.startswith("otpauth://totp/"))
        self.assertIn("Test%20Co%3Aalice", uri)
        self.assertIn(f"secret={RFC_SECRET}", uri)
        self.assertIn("issuer=Test%20Co", uri)

    @override_settings(MFA_ISSUER="Configured Issuer")
    def test_otpauth_uri_defaults_to_the_setting(self):
        uri = totp.otpauth_uri(RFC_SECRET, "alice")
        self.assertIn("Configured%20Issuer", uri)


# --- TOTPDevice (accounts/models.py) --------------------------------------


class TOTPDeviceModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        self.device = TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)

    def test_a_correct_code_verifies_and_advances_the_step(self):
        at = 1_700_000_000
        step = totp.current_step(at=at)

        self.assertTrue(self.device.verify(code_for(RFC_SECRET, at=at), at=at))

        self.device.refresh_from_db()
        self.assertEqual(self.device.last_used_step, step)

    def test_a_wrong_code_is_refused(self):
        self.assertFalse(self.device.verify("000000", at=1_700_000_000))

    def test_the_conditional_update_refuses_a_double_use(self):
        """Even a caller still holding the old ``last_used_step`` in memory
        -- as two concurrent requests racing on the same code would -- gets
        refused the second time, because the UPDATE itself is conditional.
        """
        at = 1_700_000_000
        code = code_for(RFC_SECRET, at=at)

        self.assertTrue(self.device.verify(code, at=at))

        racer = TOTPDevice.objects.get(pk=self.device.pk)
        racer.last_used_step = 0  # simulates the stale value the racer read
        self.assertFalse(racer.verify(code, at=at))

    def test_str(self):
        self.assertIn("confirmed", str(self.device))
        self.device.confirmed = False
        self.assertIn("pending", str(self.device))


# --- RecoveryCode (accounts/models.py) ------------------------------------


class RecoveryCodeModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def test_generate_set_makes_ten_codes(self):
        codes = RecoveryCode.generate_set(self.user)

        self.assertEqual(len(codes), 10)
        self.assertEqual(len(set(codes)), 10)
        self.assertEqual(RecoveryCode.objects.filter(user=self.user).count(), 10)

    def test_generating_again_replaces_the_old_set(self):
        first = RecoveryCode.generate_set(self.user)
        second = RecoveryCode.generate_set(self.user)

        self.assertEqual(RecoveryCode.objects.filter(user=self.user).count(), 10)
        self.assertFalse(set(first) & set(second))
        for code in first:
            self.assertFalse(RecoveryCode.try_use(self.user, code))

    def test_accepted_with_or_without_separators_case_insensitive(self):
        code = RecoveryCode.generate_set(self.user)[0]
        typed = f"{code[:5]}-{code[5:]}".lower()

        self.assertTrue(RecoveryCode.try_use(self.user, typed))

    def test_a_used_code_cannot_be_reused(self):
        code = RecoveryCode.generate_set(self.user)[0]

        self.assertTrue(RecoveryCode.try_use(self.user, code))
        self.assertFalse(RecoveryCode.try_use(self.user, code))

    def test_the_conditional_update_refuses_a_double_use(self):
        code = RecoveryCode.generate_set(self.user)[0]

        self.assertTrue(RecoveryCode.try_use(self.user, code))
        # Already marked used in the database; a second attempt with the
        # same code -- as a racing duplicate request would make -- finds no
        # row left matching ``used_at IS NULL`` and fails.
        self.assertFalse(RecoveryCode.try_use(self.user, code))
        self.assertEqual(
            RecoveryCode.objects.filter(user=self.user, used_at__isnull=True).count(), 9
        )

    def test_an_unknown_code_is_refused(self):
        RecoveryCode.generate_set(self.user)
        self.assertFalse(RecoveryCode.try_use(self.user, "ZZZZZZZZZZ"))

    def test_an_empty_code_is_refused(self):
        RecoveryCode.generate_set(self.user)
        self.assertFalse(RecoveryCode.try_use(self.user, ""))

    def test_str(self):
        code = RecoveryCode.objects.create(user=self.user, code_hash="x")
        self.assertIn("unused", str(code))
        code.used_at = timezone.now()
        self.assertIn("used", str(code))


class MFAEnabledHelperTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def test_no_device_is_not_enabled(self):
        self.assertFalse(mfa_enabled(self.user))

    def test_an_unconfirmed_device_is_not_enabled(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=False)
        self.assertFalse(mfa_enabled(self.user))

    def test_a_confirmed_device_is_enabled(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)
        self.assertTrue(mfa_enabled(self.user))


# --- The ticket (accounts/mfa.py) -----------------------------------------


class TicketTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def test_a_fresh_ticket_resolves_to_its_user(self):
        ticket = mfa.make_ticket(self.user)
        self.assertEqual(mfa.user_for_ticket(ticket, User), self.user)

    def test_a_tampered_ticket_is_refused(self):
        ticket = mfa.make_ticket(self.user)
        self.assertIsNone(mfa.user_for_ticket(ticket + "x", User))

    def test_garbage_is_refused(self):
        self.assertIsNone(mfa.user_for_ticket("not-a-ticket-at-all", User))

    def test_an_expired_ticket_is_refused(self):
        with patch.object(
            signing.TimestampSigner,
            "timestamp",
            lambda self: signing.b62_encode(int(time_module.time() - mfa.TICKET_MAX_AGE - 5)),
        ):
            ticket = mfa.make_ticket(self.user)

        self.assertIsNone(mfa.user_for_ticket(ticket, User))

    def test_a_ticket_dies_with_the_password(self):
        ticket = mfa.make_ticket(self.user)

        self.user.set_password("Different-Good-Pass1")
        self.user.save()

        self.assertIsNone(mfa.user_for_ticket(ticket, User))

    def test_a_ticket_for_a_deleted_user_is_refused(self):
        ticket = mfa.make_ticket(self.user)
        user_id = self.user.pk
        self.user.delete()

        self.assertIsNone(mfa.user_for_ticket(ticket, User))
        self.assertIsNone(User.objects.filter(pk=user_id).first())


# --- verify_code (accounts/mfa.py), shared by the web and the API --------


@with_cache
class VerifyCodeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        self.device = TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)

    def test_a_correct_totp_code_passes(self):
        self.assertTrue(mfa.verify_code(self.user, code_for(RFC_SECRET)))
        self.assertEqual(SecurityEvent.objects.filter(event="mfa_challenge_passed").count(), 1)

    def test_a_correct_recovery_code_passes_and_is_recorded(self):
        code = RecoveryCode.generate_set(self.user)[0]

        self.assertTrue(mfa.verify_code(self.user, code))
        self.assertEqual(SecurityEvent.objects.filter(event="recovery_code_used").count(), 1)
        self.assertEqual(SecurityEvent.objects.filter(event="mfa_challenge_passed").count(), 1)

    def test_a_wrong_code_fails_and_is_recorded(self):
        self.assertFalse(mfa.verify_code(self.user, "000000"))
        self.assertEqual(SecurityEvent.objects.filter(event="mfa_challenge_failed").count(), 1)

    def test_nothing_secret_lands_in_the_event(self):
        mfa.verify_code(self.user, code_for(RFC_SECRET))
        event = SecurityEvent.objects.get(event="mfa_challenge_passed")
        self.assertEqual(event.detail, {})

    @patch.object(ratelimit, "MFA_LIMIT", 2)
    def test_the_per_account_limit(self):
        self.assertFalse(mfa.verify_code(self.user, "000000"))
        self.assertFalse(mfa.verify_code(self.user, "000000"))

        self.assertIsNone(mfa.verify_code(self.user, code_for(RFC_SECRET)))

    @patch.object(ratelimit, "MFA_LIMIT", 2)
    def test_a_success_clears_the_limit(self):
        self.assertFalse(mfa.verify_code(self.user, "000000"))
        self.assertTrue(mfa.verify_code(self.user, code_for(RFC_SECRET)))

        self.assertFalse(mfa.verify_code(self.user, "000000"))
        self.assertFalse(ratelimit.mfa_blocked(self.user))
