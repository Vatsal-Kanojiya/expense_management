"""Multi-factor sign-in (docs/design/MFA.md): the web pages -- the login's
code step, the account page's setup/manage/disable/regenerate views -- and
the admin login's redirect to the site login.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from accounts import ratelimit, totp
from accounts.models import RecoveryCode, TOTPDevice, mfa_enabled

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


# --- The web pages -----------------------------------------------------


@with_cache
class MFALoginWebTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        self.device = TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)

    def login(self, next_url=None):
        path = "/accounts/login/"
        if next_url:
            path += f"?next={next_url}"
        return self.client.post(path, {"username": "alice", "password": PASSWORD})

    def test_login_stops_at_the_code_page_with_no_session_user(self):
        response = self.login()

        self.assertRedirects(response, "/accounts/login/mfa/")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertIn("mfa_ticket", self.client.session)

    def test_the_code_page_refuses_a_direct_visit_with_no_ticket(self):
        response = self.client.get("/accounts/login/mfa/")
        self.assertRedirects(response, "/accounts/login/")

    def test_a_correct_code_signs_in(self):
        self.login()

        response = self.client.post("/accounts/login/mfa/", {"code": code_for(RFC_SECRET)})

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
        self.assertNotIn("mfa_ticket", self.client.session)

    def test_a_wrong_code_does_not_sign_in(self):
        self.login()

        response = self.client.post("/accounts/login/mfa/", {"code": "000000"})

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_a_safe_next_is_honoured(self):
        self.login(next_url="/categories/")

        response = self.client.post("/accounts/login/mfa/", {"code": code_for(RFC_SECRET)})

        self.assertRedirects(response, "/categories/", fetch_redirect_response=False)

    def test_an_off_site_next_is_refused(self):
        self.login(next_url="https://evil.example.com/")

        response = self.client.post("/accounts/login/mfa/", {"code": code_for(RFC_SECRET)})

        self.assertRedirects(response, "/", fetch_redirect_response=False)

    @patch.object(ratelimit, "MFA_LIMIT", 2)
    def test_the_per_account_limit(self):
        self.login()

        self.client.post("/accounts/login/mfa/", {"code": "000000"})
        self.client.post("/accounts/login/mfa/", {"code": "000000"})

        response = self.client.post("/accounts/login/mfa/", {"code": code_for(RFC_SECRET)})
        self.assertEqual(response.status_code, 429)


class MFAWebManageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        self.client.force_login(self.user)

    def test_the_setup_page_shows_a_qr_code_and_secret(self):
        response = self.client.get("/accounts/mfa/setup/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("secret", response.context)
        self.assertIn("data:image/svg+xml", response.content.decode())

    def test_confirming_turns_it_on_and_shows_codes_once(self):
        setup = self.client.get("/accounts/mfa/setup/")
        secret = setup.context["secret"]

        confirm = self.client.post("/accounts/mfa/setup/", {"code": code_for(secret)})
        self.assertRedirects(
            confirm, "/accounts/mfa/recovery-codes/", fetch_redirect_response=False
        )

        codes_page = self.client.get("/accounts/mfa/recovery-codes/")
        self.assertEqual(len(codes_page.context["recovery_codes"]), 10)
        self.assertTrue(mfa_enabled(self.user))

        # Shown once: a second visit has nothing left to show.
        again = self.client.get("/accounts/mfa/recovery-codes/")
        self.assertRedirects(again, "/accounts/mfa/")

    def test_a_wrong_confirm_code_does_not_turn_it_on(self):
        self.client.get("/accounts/mfa/setup/")

        response = self.client.post("/accounts/mfa/setup/", {"code": "000000"})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(mfa_enabled(self.user))

    def test_disable_needs_password_and_code(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)
        RecoveryCode.generate_set(self.user)

        response = self.client.post(
            "/accounts/mfa/disable/", {"password": PASSWORD, "code": code_for(RFC_SECRET)}
        )

        self.assertRedirects(response, "/accounts/mfa/")
        self.assertFalse(mfa_enabled(self.user))

    def test_disable_with_wrong_password_does_nothing(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)

        self.client.post(
            "/accounts/mfa/disable/", {"password": "wrong", "code": code_for(RFC_SECRET)}
        )

        self.assertTrue(mfa_enabled(self.user))

    def test_regenerate_shows_new_codes_once(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)
        old = RecoveryCode.generate_set(self.user)

        response = self.client.post(
            "/accounts/mfa/recovery-codes/regenerate/", {"code": code_for(RFC_SECRET)}
        )
        self.assertRedirects(
            response, "/accounts/mfa/recovery-codes/", fetch_redirect_response=False
        )

        codes_page = self.client.get("/accounts/mfa/recovery-codes/")
        new = codes_page.context["recovery_codes"]
        self.assertFalse(set(old) & set(new))

    def test_the_manage_page_requires_sign_in(self):
        self.client.logout()
        response = self.client.get("/accounts/mfa/")
        self.assertEqual(response.status_code, 302)

    def test_visiting_setup_when_already_enabled_redirects_to_manage(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)

        response = self.client.get("/accounts/mfa/setup/")

        self.assertRedirects(response, "/accounts/mfa/")

    def test_confirming_when_already_enabled_redirects_to_manage(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)

        response = self.client.post("/accounts/mfa/setup/", {"code": "000000"})

        self.assertRedirects(response, "/accounts/mfa/")

    def test_confirming_with_nothing_pending_sends_back_to_setup(self):
        response = self.client.post("/accounts/mfa/setup/", {"code": "000000"})
        self.assertRedirects(response, "/accounts/mfa/setup/")

    def test_disable_when_not_enabled_redirects(self):
        response = self.client.post(
            "/accounts/mfa/disable/", {"password": PASSWORD, "code": "000000"}
        )
        self.assertRedirects(response, "/accounts/mfa/")

    def test_disable_with_wrong_code_redirects_with_a_message(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)

        response = self.client.post(
            "/accounts/mfa/disable/", {"password": PASSWORD, "code": "000000"}
        )

        self.assertRedirects(response, "/accounts/mfa/")
        self.assertTrue(mfa_enabled(self.user))

    def test_regenerate_when_not_enabled_redirects(self):
        response = self.client.post("/accounts/mfa/recovery-codes/regenerate/", {"code": "000000"})
        self.assertRedirects(response, "/accounts/mfa/")

    def test_regenerate_with_wrong_code_redirects_with_a_message(self):
        TOTPDevice.objects.create(user=self.user, secret=RFC_SECRET, confirmed=True)

        response = self.client.post("/accounts/mfa/recovery-codes/regenerate/", {"code": "000000"})

        self.assertRedirects(response, "/accounts/mfa/")


# --- The admin login redirect --------------------------------------------


class AdminLoginRedirectTests(TestCase):
    def test_the_admin_login_redirects_to_the_site_login(self):
        response = self.client.get("/admin/login/")
        self.assertRedirects(
            response, "/accounts/login/?next=/admin/", fetch_redirect_response=False
        )
