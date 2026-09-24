"""The account API (phase 20.3): the web's rules, over JSON and bearer tokens."""

import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts import ratelimit
from expenses.models import Category, Participant

User = get_user_model()

with_cache = override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)


def url(name):
    return reverse(f"api:v1:{name}")


class AuthApiTestCase(TestCase):
    password = "Str0ng-Enough-Pass"

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", cls.password)

    def post(self, name, data, **extra):
        return self.client.post(url(name), data, content_type="application/json", **extra)

    def login(self, username="alice", password=None):
        return self.post(
            "auth-login", {"username": username, "password": password or self.password}
        )

    def bearer(self, access):
        return {"HTTP_AUTHORIZATION": f"Bearer {access}"}

    @staticmethod
    def link_parts(body, prefix):
        match = re.search(prefix + r"([^/\s]+)/([^/\s]+)", body)
        return {"uid": match.group(1), "token": match.group(2)}


class SignupTests(AuthApiTestCase):
    payload = {
        "username": "bella",
        "email": "Bella@Example.com",
        "password": "Str0ng-Enough-Pass",
        "password_confirm": "Str0ng-Enough-Pass",
    }

    @override_settings(FRONTEND_URL="")  # the default, whatever the environment says
    def test_signup_creates_an_inactive_account_and_mails_a_link(self):
        response = self.post("auth-signup", self.payload)

        self.assertEqual(response.status_code, 201, response.content)
        user = User.objects.get(username="bella")
        self.assertFalse(user.is_active)
        self.assertEqual(user.email, "bella@example.com")  # the web form's lower-casing
        self.assertTrue(Participant.objects.filter(user=user, is_self=True).exists())
        self.assertIn("/accounts/verify/", mail.outbox[0].body)

    @override_settings(FRONTEND_URL="https://app.example.com")
    def test_with_a_frontend_the_link_goes_to_the_frontend(self):
        self.post("auth-signup", self.payload)

        self.assertIn("https://app.example.com/verify-email/", mail.outbox[0].body)

    def test_the_web_password_rules_apply_under_api_field_names(self):
        response = self.post(
            "auth-signup", {**self.payload, "password": "short", "password_confirm": "other"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("password_confirm", response.json())
        self.assertFalse(User.objects.filter(username="bella").exists())

    def test_an_email_already_in_use_is_refused(self):
        response = self.post("auth-signup", {**self.payload, "email": "ALICE@example.com"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.json())

    @override_settings(FRONTEND_URL="https://app.example.com")
    def test_the_mailed_link_verifies_once_and_signs_in(self):
        self.post("auth-signup", self.payload)
        link = self.link_parts(mail.outbox[0].body, "/verify-email/")

        first = self.post("auth-verify-email", link)
        again = self.post("auth-verify-email", link)

        self.assertEqual(first.status_code, 200)
        self.assertIn("access", first.json())
        self.assertTrue(User.objects.get(username="bella").is_active)
        self.assertEqual(again.status_code, 400)  # single use: is_active is in the hash
        self.assertEqual(again.json()["code"], "invalid_link")


class LoginTests(AuthApiTestCase):
    def test_login_returns_tokens_and_the_profile(self):
        response = self.login()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["user"]["username"], "alice")
        me = Participant.objects.get(user=self.alice, is_self=True)
        self.assertEqual(body["user"]["self_participant"], {"id": me.id, "name": me.name})
        self.assertEqual(
            self.client.get(url("me"), **self.bearer(body["access"])).json()["username"], "alice"
        )

    def test_a_wrong_password_is_a_401(self):
        response = self.login(password="nope")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "invalid_credentials")

    def test_an_unverified_account_is_told_why(self):
        User.objects.create_user("new", "new@example.com", self.password, is_active=False)

        right = self.login("new")
        wrong = self.login("new", "nope")

        self.assertEqual(right.status_code, 403)
        self.assertEqual(right.json()["code"], "email_not_verified")
        # Without the password, an unverified account looks like any failure.
        self.assertEqual(wrong.status_code, 401)

    @with_cache
    def test_login_is_rate_limited_on_the_web_budget(self):
        cache.clear()
        for _ in range(ratelimit.LOGIN_LIMIT):
            self.login(password="nope")

        response = self.login()  # even the right password

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["code"], "rate_limited")

    @with_cache
    def test_web_and_api_attempts_share_one_budget(self):
        cache.clear()
        for _ in range(ratelimit.LOGIN_LIMIT):
            self.client.post("/accounts/login/", {"username": "alice", "password": "nope"})

        self.assertEqual(self.login().status_code, 429)


class TokenLifecycleTests(AuthApiTestCase):
    def test_refresh_rotates_and_the_old_refresh_token_dies(self):
        tokens = self.login().json()

        first = self.post("auth-refresh", {"refresh": tokens["refresh"]})
        replay = self.post("auth-refresh", {"refresh": tokens["refresh"]})

        self.assertEqual(first.status_code, 200)
        self.assertNotEqual(first.json()["refresh"], tokens["refresh"])
        self.assertEqual(replay.status_code, 401)

    def test_logout_revokes_the_refresh_token(self):
        tokens = self.login().json()

        response = self.post("auth-logout", {"refresh": tokens["refresh"]})

        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.post("auth-refresh", {"refresh": tokens["refresh"]}).status_code, 401)
        self.assertEqual(self.post("auth-logout", {"refresh": tokens["refresh"]}).status_code, 400)

    def test_a_password_changed_on_a_django_page_ends_api_access_tokens(self):
        access = self.login().json()["access"]
        self.alice.set_password("An0ther-Good-Pass")
        self.alice.save()

        response = self.client.get(url("me"), **self.bearer(access))

        self.assertEqual(response.status_code, 401)


class PasswordTests(AuthApiTestCase):
    def test_change_needs_the_old_password(self):
        access = self.login().json()["access"]

        response = self.post(
            "auth-password-change",
            {
                "old_password": "nope",
                "new_password": "An0ther-Good-Pass",
                "new_password_confirm": "An0ther-Good-Pass",
            },
            **self.bearer(access),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("old_password", response.json())

    def test_change_keeps_this_device_and_signs_out_the_others(self):
        other_device = self.login().json()
        this_device = self.login().json()

        response = self.post(
            "auth-password-change",
            {
                "old_password": self.password,
                "new_password": "An0ther-Good-Pass",
                "new_password_confirm": "An0ther-Good-Pass",
            },
            **self.bearer(this_device["access"]),
        )

        self.assertEqual(response.status_code, 200)
        fresh = response.json()["access"]
        self.assertEqual(self.client.get(url("me"), **self.bearer(fresh)).status_code, 200)
        self.assertEqual(
            self.client.get(url("me"), **self.bearer(other_device["access"])).status_code, 401
        )
        self.assertEqual(
            self.post("auth-refresh", {"refresh": other_device["refresh"]}).status_code, 401
        )

    def test_reset_does_not_reveal_whether_an_email_exists(self):
        known = self.post("auth-password-reset", {"email": "alice@example.com"})
        unknown = self.post("auth-password-reset", {"email": "nobody@example.com"})

        self.assertEqual(known.json(), unknown.json())
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(FRONTEND_URL="https://app.example.com")
    def test_reset_through_the_frontend_link(self):
        old = self.login().json()
        self.post("auth-password-reset", {"email": "alice@example.com"})
        link = self.link_parts(mail.outbox[0].body, "https://app.example.com/reset-password/")

        response = self.post(
            "auth-password-reset-confirm",
            {
                **link,
                "new_password": "An0ther-Good-Pass",
                "new_password_confirm": "An0ther-Good-Pass",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.login(password="An0ther-Good-Pass").status_code, 200)
        self.assertEqual(self.post("auth-refresh", {"refresh": old["refresh"]}).status_code, 401)
        replay = self.post(
            "auth-password-reset-confirm",
            {
                **link,
                "new_password": "Th1rd-Good-Pass!",
                "new_password_confirm": "Th1rd-Good-Pass!",
            },
        )
        self.assertEqual(replay.status_code, 400)

    @with_cache
    def test_reset_is_rate_limited(self):
        cache.clear()
        for _ in range(ratelimit.RESET_LIMIT):
            self.post("auth-password-reset", {"email": "alice@example.com"})

        response = self.post("auth-password-reset", {"email": "alice@example.com"})

        self.assertEqual(response.status_code, 429)


class MeTests(AuthApiTestCase):
    def setUp(self):
        self.access = self.login().json()["access"]

    def test_a_name_can_be_changed_but_not_the_username(self):
        response = self.client.patch(
            url("me"),
            {"first_name": "Alice", "username": "mallory"},
            content_type="application/json",
            **self.bearer(self.access),
        )

        self.assertEqual(response.status_code, 200)
        self.alice.refresh_from_db()
        self.assertEqual((self.alice.first_name, self.alice.username), ("Alice", "alice"))

    def test_deleting_needs_the_username_typed_out(self):
        response = self.client.delete(
            url("me"),
            {"confirm": "alic"},
            content_type="application/json",
            **self.bearer(self.access),
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(User.objects.filter(pk=self.alice.pk).exists())

    def test_deleting_removes_the_account_and_its_data(self):
        Category.objects.create(user=self.alice, name="Food")

        response = self.client.delete(
            url("me"),
            {"confirm": "alice"},
            content_type="application/json",
            **self.bearer(self.access),
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(User.objects.filter(username="alice").exists())
        self.assertFalse(Category.objects.filter(name="Food").exists())
        self.assertEqual(self.client.get(url("me"), **self.bearer(self.access)).status_code, 401)

    def test_anonymous_is_refused(self):
        self.assertEqual(self.client.get(url("me")).status_code, 401)
