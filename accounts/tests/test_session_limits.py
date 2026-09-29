"""Sign-in limits per account (docs/design/SESSION_LIMITS.md).

Part 1: a cap on wrong passwords per account, whatever the address.
Part 2 (devices) is added further down this file.
"""

from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from accounts import devices, google, ratelimit, totp
from accounts.models import SecurityEvent, SignedInDevice, TOTPDevice
from accounts.verification import token_generator as verification_token

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


GOOGLE_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
with_google = override_settings(GOOGLE_OAUTH_CLIENT_ID=GOOGLE_CLIENT_ID)


def with_google_settings():
    return override_settings(GOOGLE_OAUTH_CLIENT_ID=GOOGLE_CLIENT_ID)


def google_claims(email="alice@example.com"):
    return {
        "iss": "https://accounts.google.com",
        "aud": GOOGLE_CLIENT_ID,
        "sub": "1234567890",
        "email": email,
        "email_verified": True,
        "exp": 9999999999,
    }


def mock_google_verify():
    return patch.object(google.google_id_token, "verify_oauth2_token", return_value=google_claims())


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

    @with_google
    def test_google_sign_in_is_not_blocked_by_it(self):
        self.fail_from_many_addresses(ratelimit.LOGIN_ACCOUNT_LIMIT)

        with mock_google_verify():
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


# --- Part 2: at most two devices signed in at a time ------------------------

RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
WEB_UA = "Mozilla/5.0 (X11; Linux) Firefox/130"
APP_UA = "ExpenseApp/1.0 (Android 15)"


def code_for(secret):
    return totp._hotp(secret, totp.current_step())


class DeviceTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        cls.bob = User.objects.create_user("bob", "bob@example.com", PASSWORD)

    # -- ways to sign in, each on its own "device" ---------------------------

    def web_device(self, user="alice", ua=WEB_UA):
        """Sign in on the login page with a fresh browser; returns its client."""
        client = self.client_class()
        response = client.post(
            "/accounts/login/",
            {"username": user, "password": PASSWORD},
            HTTP_USER_AGENT=ua,
        )
        self.assertEqual(response.status_code, 302, "the web sign-in should have worked")
        return client

    def api_device(self, user="alice", ua=APP_UA):
        """Sign in through the API; returns the token pair."""
        response = self.client_class().post(
            "/api/v1/auth/login/",
            {"username": user, "password": PASSWORD},
            content_type="application/json",
            HTTP_USER_AGENT=ua,
        )
        self.assertEqual(response.status_code, 200, "the API sign-in should have worked")
        return response.json()

    def refresh(self, pair):
        return self.client_class().post(
            "/api/v1/auth/refresh/", {"refresh": pair["refresh"]}, content_type="application/json"
        )

    def signed_in(self, client):
        """Whether this browser is still signed in."""
        return client.get(reverse("accounts:mfa")).status_code == 200

    def devices_of(self, user="alice"):
        return list(SignedInDevice.objects.filter(user__username=user))

    def age(self, device, minutes):
        """Make a device look like it was last seen `minutes` ago."""
        SignedInDevice.objects.filter(pk=device.pk).update(
            last_seen_at=timezone.now() - timedelta(minutes=minutes)
        )


class RegisteringTests(DeviceTestCase):
    def test_a_web_sign_in_registers_the_session(self):
        client = self.web_device()

        (device,) = self.devices_of()
        self.assertEqual(device.kind, "web")
        self.assertEqual(device.session_key, client.session.session_key)
        self.assertEqual(device.refresh_jti, "")
        self.assertEqual(device.label, WEB_UA)

    def test_an_api_sign_in_registers_the_refresh_token(self):
        pair = self.api_device()

        (device,) = self.devices_of()
        self.assertEqual(device.kind, "api")
        self.assertEqual(device.session_key, "")
        self.assertEqual(device.refresh_jti, str(RefreshToken(pair["refresh"])["jti"]))
        self.assertEqual(device.label, APP_UA)

    def test_the_label_is_the_user_agent_cut_to_200_characters(self):
        self.api_device(ua="x" * 500)

        self.assertEqual(self.devices_of()[0].label, "x" * 200)

    def test_a_missing_user_agent_gives_an_empty_label(self):
        self.client_class().post(
            "/api/v1/auth/login/",
            {"username": "alice", "password": PASSWORD},
            content_type="application/json",
        )

        self.assertEqual(self.devices_of()[0].label, "")

    def test_another_accounts_devices_are_not_counted(self):
        self.web_device("alice")
        self.web_device("alice")
        self.web_device("bob")

        self.assertEqual(len(self.devices_of("alice")), 2)
        self.assertEqual(len(self.devices_of("bob")), 1)

    def test_an_mfa_web_sign_in_registers_only_after_the_code(self):
        TOTPDevice.objects.create(user=self.alice, secret=RFC_SECRET, confirmed=True)
        client = self.client_class()
        client.post("/accounts/login/", {"username": "alice", "password": PASSWORD})
        self.assertEqual(self.devices_of(), [])

        client.post(reverse("accounts:login_mfa"), {"code": code_for(RFC_SECRET)})

        (device,) = self.devices_of()
        self.assertEqual(device.session_key, client.session.session_key)
        self.assertTrue(self.signed_in(client))

    def test_an_mfa_api_sign_in_registers_only_after_the_code(self):
        TOTPDevice.objects.create(user=self.alice, secret=RFC_SECRET, confirmed=True)
        first = self.client.post(
            "/api/v1/auth/login/",
            {"username": "alice", "password": PASSWORD},
            content_type="application/json",
        ).json()
        self.assertEqual(self.devices_of(), [])

        self.client.post(
            "/api/v1/auth/mfa/verify/",
            {"mfa_ticket": first["mfa_ticket"], "code": code_for(RFC_SECRET)},
            content_type="application/json",
        )

        self.assertEqual([d.kind for d in self.devices_of()], ["api"])

    @with_google
    def test_google_sign_in_registers_on_the_web_and_the_api(self):
        with mock_google_verify():
            web = self.client_class()
            web.post(reverse("accounts:google_login"), {"credential": "x"})
            api = self.client_class().post(
                "/api/v1/auth/google/", {"credential": "x"}, content_type="application/json"
            )

        self.assertEqual(api.status_code, 200)
        self.assertEqual(sorted(d.kind for d in self.devices_of()), ["api", "web"])

    def test_verifying_an_email_over_the_api_registers_a_device(self):
        pending = User.objects.create_user("carol", "carol@example.com", PASSWORD, is_active=False)
        uid = urlsafe_base64_encode(force_bytes(pending.pk))
        token = verification_token.make_token(pending)

        response = self.client.post(
            "/api/v1/auth/verify-email/",
            {"uid": uid, "token": token},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([d.kind for d in self.devices_of("carol")], ["api"])

    def test_verifying_an_email_on_the_web_registers_a_device(self):
        pending = User.objects.create_user("carol", "carol@example.com", PASSWORD, is_active=False)
        uid = urlsafe_base64_encode(force_bytes(pending.pk))
        token = verification_token.make_token(pending)

        self.client.get(reverse("accounts:verify_email", args=[uid, token]))

        self.assertEqual([d.kind for d in self.devices_of("carol")], ["web"])

    def test_signing_in_again_on_the_same_browser_is_still_one_device(self):
        client = self.web_device()
        # login() on a session that already has this user rotates its key.
        with mock_google_verify(), with_google_settings():
            client.post(reverse("accounts:google_login"), {"credential": "x"})

        (device,) = self.devices_of()
        self.assertEqual(device.session_key, client.session.session_key)


class LimitTests(DeviceTestCase):
    def test_a_third_web_sign_in_ends_the_oldest(self):
        first = self.web_device()
        second = self.web_device()
        third = self.web_device()

        self.assertFalse(self.signed_in(first))
        self.assertTrue(self.signed_in(second))
        self.assertTrue(self.signed_in(third))
        self.assertEqual(len(self.devices_of()), 2)

    def test_the_ended_web_session_is_anonymous_on_its_next_request(self):
        first = self.web_device()
        self.web_device()
        self.web_device()

        response = first.get(reverse("accounts:mfa"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)
        self.assertNotIn("_auth_user_id", first.session)

    def test_a_third_api_sign_in_ends_the_oldest_and_its_refresh_gets_401(self):
        first = self.api_device()
        second = self.api_device()
        third = self.api_device()

        self.assertEqual(self.refresh(first).status_code, 401)
        self.assertEqual(self.refresh(second).status_code, 200)
        self.assertEqual(self.refresh(third).status_code, 200)
        self.assertEqual(len(self.devices_of()), 2)

    def test_the_ended_api_devices_access_token_keeps_working_until_it_expires(self):
        # The known limitation (docs/design/SESSION_LIMITS.md): what ends is
        # the ability to refresh.
        first = self.api_device()
        self.api_device()
        self.api_device()

        response = self.client.get("/api/v1/me/", HTTP_AUTHORIZATION=f"Bearer {first['access']}")

        self.assertEqual(response.status_code, 200)

    def test_web_then_api_then_web_ends_the_oldest_of_the_mix(self):
        first = self.web_device()
        second = self.api_device()
        third = self.web_device()

        self.assertFalse(self.signed_in(first))
        self.assertEqual(self.refresh(second).status_code, 200)
        self.assertTrue(self.signed_in(third))

    def test_api_then_web_then_api_ends_the_oldest_of_the_mix(self):
        first = self.api_device()
        second = self.web_device()
        self.api_device()

        self.assertEqual(self.refresh(first).status_code, 401)
        self.assertTrue(self.signed_in(second))

    def test_the_oldest_is_by_last_seen_not_by_when_it_signed_in(self):
        first = self.api_device()
        second = self.api_device()
        (older, newer) = self.devices_of()
        # The first device was refreshed since; the second has been idle.
        self.age(older, 1)
        self.age(newer, 60)

        self.api_device()

        self.assertEqual(self.refresh(first).status_code, 200)
        self.assertEqual(self.refresh(second).status_code, 401)

    def test_the_new_sign_in_always_succeeds(self):
        for _ in range(5):
            self.assertTrue(self.signed_in(self.web_device()))

    def test_ending_a_device_is_recorded_with_its_kind_and_label(self):
        self.web_device(ua="Old Browser")
        self.api_device(ua="Old App")
        self.web_device()
        self.api_device()

        events = SecurityEvent.objects.filter(event="device_signed_out").order_by("id")
        self.assertEqual(
            [(e.detail["kind"], e.detail["label"], e.username) for e in events],
            [("web", "Old Browser", "alice"), ("api", "Old App", "alice")],
        )
        self.assertEqual(events[0].detail["reason"], "limit")

    def test_one_accounts_limit_does_not_touch_another(self):
        bob = self.web_device("bob")
        for _ in range(3):
            self.web_device("alice")

        self.assertTrue(self.signed_in(bob))

    @override_settings(MAX_SIGNED_IN_DEVICES=3)
    def test_the_limit_is_a_setting(self):
        first = self.web_device()
        self.web_device()
        self.web_device()
        self.assertTrue(self.signed_in(first))

        self.web_device()

        self.assertFalse(self.signed_in(first))
        self.assertEqual(len(self.devices_of()), 3)

    @override_settings(MAX_SIGNED_IN_DEVICES=1)
    def test_a_limit_of_one_keeps_only_the_latest(self):
        first = self.web_device()
        second = self.web_device()

        self.assertFalse(self.signed_in(first))
        self.assertTrue(self.signed_in(second))

    @override_settings(MAX_SIGNED_IN_DEVICES=0)
    def test_a_limit_below_one_is_treated_as_one(self):
        self.assertEqual(devices.limit(), 1)
        first = self.web_device()
        second = self.web_device()

        self.assertFalse(self.signed_in(first))
        self.assertTrue(self.signed_in(second))

    def test_dropping_back_under_a_lowered_limit_takes_effect_at_the_next_sign_in(self):
        with override_settings(MAX_SIGNED_IN_DEVICES=4):
            for _ in range(4):
                self.web_device()

        self.web_device()

        self.assertEqual(len(self.devices_of()), 2)


class DeadRecordTests(DeviceTestCase):
    def test_a_web_session_that_expired_does_not_push_out_a_live_device(self):
        gone = self.web_device()
        Session.objects.filter(session_key=gone.session.session_key).update(
            expire_date=timezone.now() - timedelta(minutes=1)
        )
        live = self.web_device()

        third = self.web_device()

        self.assertTrue(self.signed_in(live))
        self.assertTrue(self.signed_in(third))
        self.assertEqual(SecurityEvent.objects.filter(event="device_signed_out").count(), 0)

    def test_a_web_session_that_no_longer_exists_does_not_push_out_a_live_device(self):
        gone = self.web_device()
        Session.objects.filter(session_key=gone.session.session_key).delete()
        live = self.web_device()

        third = self.web_device()

        self.assertTrue(self.signed_in(live))
        self.assertTrue(self.signed_in(third))
        self.assertEqual(len(self.devices_of()), 2)

    def test_an_expired_api_token_does_not_push_out_a_live_device(self):
        stale = self.api_device()
        OutstandingToken.objects.filter(jti=RefreshToken(stale["refresh"])["jti"]).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        live = self.api_device()

        third = self.api_device()

        self.assertEqual(self.refresh(live).status_code, 200)
        self.assertEqual(self.refresh(third).status_code, 200)
        self.assertEqual(SecurityEvent.objects.filter(event="device_signed_out").count(), 0)

    def test_a_blacklisted_api_token_does_not_push_out_a_live_device(self):
        revoked = self.api_device()
        RefreshToken(revoked["refresh"]).blacklist()
        live = self.api_device()

        third = self.api_device()

        self.assertEqual(self.refresh(live).status_code, 200)
        self.assertEqual(self.refresh(third).status_code, 200)
        self.assertEqual(len(self.devices_of()), 2)

    def test_a_session_ended_by_a_password_change_elsewhere_does_not_count(self):
        # Changing the password leaves other sessions' rows in place while
        # Django refuses to load them. They must not hold a slot.
        other = self.web_device()
        changer = self.web_device()
        changer.post(
            reverse("accounts:password_change"),
            {
                "old_password": PASSWORD,
                "new_password1": "An0ther-Str0ng-Pass",
                "new_password2": "An0ther-Str0ng-Pass",
            },
        )
        self.assertFalse(self.signed_in(other))

        newest = self.client_class()
        newest.post("/accounts/login/", {"username": "alice", "password": "An0ther-Str0ng-Pass"})

        self.assertTrue(self.signed_in(changer))
        self.assertTrue(self.signed_in(newest))
        self.assertEqual(len(self.devices_of()), 2)

    def test_a_session_of_another_user_under_the_key_is_dead(self):
        gone = self.web_device()
        # Same key, another account (e.g. the row was reused): not alice's.
        Session.objects.filter(session_key=gone.session.session_key).update(
            session_data=Session.objects.encode({"_auth_user_id": str(self.bob.pk)})
        )

        devices.prune(self.alice)

        self.assertEqual(self.devices_of(), [])

    def test_a_session_with_unreadable_data_is_dead(self):
        gone = self.web_device()
        Session.objects.filter(session_key=gone.session.session_key).update(session_data="junk")

        devices.prune(self.alice)

        self.assertEqual(self.devices_of(), [])

    def test_a_session_signed_with_a_fallback_key_still_counts(self):
        client = self.web_device()
        with override_settings(
            SECRET_KEY="a-different-key-of-the-usual-length-0123456789-abcdefghij",
            SECRET_KEY_FALLBACKS=[settings.SECRET_KEY],
        ):
            devices.prune(User.objects.get(pk=self.alice.pk))

        self.assertEqual(len(self.devices_of()), 1)
        self.assertTrue(self.signed_in(client))


class RefreshTests(DeviceTestCase):
    def test_a_refresh_moves_the_record_to_the_new_token(self):
        pair = self.api_device()
        (before,) = self.devices_of()
        self.age(before, 30)

        response = self.refresh(pair)

        (after,) = self.devices_of()
        self.assertEqual(after.pk, before.pk)
        self.assertEqual(after.refresh_jti, str(RefreshToken(response.json()["refresh"])["jti"]))
        self.assertNotEqual(after.refresh_jti, before.refresh_jti)
        self.assertGreater(after.last_seen_at, timezone.now() - timedelta(minutes=1))
        self.assertEqual(after.created_at, before.created_at)

    def test_a_chain_of_refreshes_stays_one_device(self):
        pair = self.api_device()
        for _ in range(3):
            pair = self.refresh(pair).json()

        self.assertEqual(len(self.devices_of()), 1)

    def test_a_refresh_with_a_bad_token_changes_nothing(self):
        self.api_device()

        for body in ({"refresh": "junk"}, {"refresh": 5}, {}, ["x"]):
            response = self.client.post(
                "/api/v1/auth/refresh/", body, content_type="application/json"
            )
            self.assertEqual(response.status_code, 401 if body != {} and body != ["x"] else 400)

        self.assertEqual(len(self.devices_of()), 1)

    def test_a_refresh_token_from_before_the_limit_existed_is_registered_when_used(self):
        legacy = RefreshToken.for_user(self.alice)  # issued the way it used to be: no record
        self.assertEqual(self.devices_of(), [])

        response = self.client.post(
            "/api/v1/auth/refresh/", {"refresh": str(legacy)}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        (device,) = self.devices_of()
        self.assertEqual(device.refresh_jti, str(RefreshToken(response.json()["refresh"])["jti"]))

    def test_registering_such_a_token_can_end_the_oldest_device(self):
        first = self.web_device()
        self.web_device()
        legacy = RefreshToken.for_user(self.alice)

        self.client.post(
            "/api/v1/auth/refresh/", {"refresh": str(legacy)}, content_type="application/json"
        )

        self.assertFalse(self.signed_in(first))
        self.assertEqual(len(self.devices_of()), 2)


class SigningOutNormallyTests(DeviceTestCase):
    def test_a_web_logout_removes_the_record(self):
        client = self.web_device()
        self.web_device()

        client.post(reverse("accounts:logout"))

        self.assertEqual(len(self.devices_of()), 1)
        self.assertFalse(self.signed_in(client))
        self.assertEqual(SecurityEvent.objects.filter(event="device_signed_out").count(), 0)

    def test_an_anonymous_logout_changes_nothing(self):
        self.web_device()

        self.client_class().post(reverse("accounts:logout"))

        self.assertEqual(len(self.devices_of()), 1)

    def test_an_api_logout_removes_the_record(self):
        pair = self.api_device()
        self.api_device()

        response = self.client.post(
            "/api/v1/auth/logout/", {"refresh": pair["refresh"]}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(len(self.devices_of()), 1)

    def test_a_third_sign_in_after_a_logout_ends_nobody(self):
        first = self.web_device()
        second = self.web_device()
        second.post(reverse("accounts:logout"))

        third = self.web_device()

        self.assertTrue(self.signed_in(first))
        self.assertTrue(self.signed_in(third))

    def test_deleting_the_account_removes_its_records(self):
        client = self.web_device()
        self.api_device()

        client.post(reverse("accounts:delete_account"), {"confirm": "alice"})

        self.assertEqual(SignedInDevice.objects.count(), 0)

    def test_deleting_the_account_over_the_api_removes_its_records(self):
        pair = self.api_device()

        self.client.delete(
            "/api/v1/me/",
            {"confirm": "alice"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {pair['access']}",
        )

        self.assertEqual(SignedInDevice.objects.count(), 0)


class PasswordChangeTests(DeviceTestCase):
    NEW = "An0ther-Str0ng-Pass"

    def test_the_current_web_device_survives_a_web_password_change(self):
        client = self.web_device()
        old_key = client.session.session_key

        client.post(
            reverse("accounts:password_change"),
            {"old_password": PASSWORD, "new_password1": self.NEW, "new_password2": self.NEW},
        )

        self.assertNotEqual(client.session.session_key, old_key)
        (device,) = self.devices_of()
        self.assertEqual(device.session_key, client.session.session_key)
        self.assertTrue(self.signed_in(client))

    def test_a_web_password_change_signs_out_the_api_devices_and_forgets_them(self):
        pair = self.api_device()
        client = self.web_device()

        client.post(
            reverse("accounts:password_change"),
            {"old_password": PASSWORD, "new_password1": self.NEW, "new_password2": self.NEW},
        )

        self.assertEqual(self.refresh(pair).status_code, 401)
        self.assertEqual([d.kind for d in self.devices_of()], ["web"])

    def test_an_api_password_change_keeps_the_caller_as_one_device(self):
        pair = self.api_device()
        other = self.api_device()

        response = self.client.post(
            "/api/v1/auth/password/change/",
            {"old_password": PASSWORD, "new_password": self.NEW, "new_password_confirm": self.NEW},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {pair['access']}",
        )

        self.assertEqual(response.status_code, 200)
        (device,) = self.devices_of()
        self.assertEqual(device.refresh_jti, str(RefreshToken(response.json()["refresh"])["jti"]))
        self.assertEqual(self.refresh(other).status_code, 401)

    def test_an_api_password_change_from_a_web_session_keeps_that_session(self):
        client = self.web_device()

        response = client.post(
            "/api/v1/auth/password/change/",
            {"old_password": PASSWORD, "new_password": self.NEW, "new_password_confirm": self.NEW},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.signed_in(client))
        web = [d for d in self.devices_of() if d.kind == "web"]
        self.assertEqual([d.session_key for d in web], [client.session.session_key])

    def test_a_password_reset_forgets_every_api_device(self):
        self.api_device()
        self.api_device()
        self.alice.refresh_from_db()  # the sign-ins above moved last_login
        uid = urlsafe_base64_encode(force_bytes(self.alice.pk))
        token = default_token_generator.make_token(self.alice)

        response = self.client.post(
            "/api/v1/auth/password/reset/confirm/",
            {
                "uid": uid,
                "token": token,
                "new_password": self.NEW,
                "new_password_confirm": self.NEW,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.devices_of(), [])

    def test_the_mfa_pages_do_not_lose_the_current_device(self):
        client = self.web_device()
        client.get(reverse("accounts:mfa_setup"))
        secret = TOTPDevice.objects.get(user=self.alice).secret

        client.post(reverse("accounts:mfa_setup"), {"code": code_for(secret)})

        self.assertTrue(self.signed_in(client))
        (device,) = self.devices_of()
        self.assertEqual(device.session_key, client.session.session_key)

    def test_cycling_a_signed_in_sessions_key_moves_its_record(self):
        client = self.web_device()
        old_key = client.session.session_key
        request = RequestFactory().get("/")
        request.session = client.session

        devices.cycle_session_key(request)

        self.assertNotEqual(request.session.session_key, old_key)
        (device,) = self.devices_of()
        self.assertEqual(device.session_key, request.session.session_key)

    def test_a_signed_in_user_starting_a_google_sign_in_for_an_mfa_account_keeps_their_device(self):
        TOTPDevice.objects.create(user=self.alice, secret=RFC_SECRET, confirmed=True)
        client = self.client_class()
        client.force_login(self.alice)
        (before,) = self.devices_of()

        with mock_google_verify(), with_google_settings():
            client.post(reverse("accounts:google_login"), {"credential": "x"})

        (after,) = self.devices_of()
        self.assertEqual(after.pk, before.pk)
        self.assertEqual(after.session_key, client.session.session_key)
        self.assertNotEqual(after.session_key, before.session_key)


class NoSessionTests(DeviceTestCase):
    def test_a_login_without_a_session_key_registers_nothing(self):
        # e.g. a signed-cookie session engine, which has no server-side key.
        request = RequestFactory().get("/")

        self.assertIsNone(devices.register_web(request, self.alice))
        self.assertEqual(self.devices_of(), [])
