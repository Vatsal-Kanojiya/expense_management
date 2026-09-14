"""Authentication flows: login, logout, signup, password change and reset.

Security properties are asserted alongside the happy paths, because in
auth the interesting failures are silent — a working login that also
leaks which usernames exist is still a broken login.
"""

import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class LoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            "alice", email="alice@example.com", password="correct-horse-42"
        )

    def test_login_page_renders(self):
        response = self.client.get(reverse("accounts:login"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/login.html")

    def test_valid_credentials_sign_the_user_in(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "alice", "password": "correct-horse-42"},
        )

        self.assertRedirects(response, reverse("expenses:dashboard"))

    def test_wrong_password_is_rejected(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "alice", "password": "wrong"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["user"].is_authenticated)

    def test_error_does_not_reveal_whether_the_username_exists(self):
        # A different message for "no such user" versus "wrong password"
        # turns the login form into a username oracle.
        real = self.client.post(
            reverse("accounts:login"), {"username": "alice", "password": "wrong"}
        )
        fake = self.client.post(
            reverse("accounts:login"), {"username": "nobody", "password": "wrong"}
        )

        self.assertEqual(
            real.context["form"].non_field_errors(),
            fake.context["form"].non_field_errors(),
        )

    def test_next_parameter_returns_the_user_to_their_destination(self):
        target = reverse("expenses:category_list")

        response = self.client.post(
            f"{reverse('accounts:login')}?next={target}",
            {"username": "alice", "password": "correct-horse-42"},
        )

        self.assertRedirects(response, target)

    def test_open_redirect_is_refused(self):
        # ?next= pointing off-site must not be honoured, or the login page
        # becomes a phishing springboard.
        response = self.client.post(
            f"{reverse('accounts:login')}?next=https://evil.example.com/",
            {"username": "alice", "password": "correct-horse-42"},
        )

        self.assertRedirects(response, reverse("expenses:dashboard"))

    def test_authenticated_user_is_redirected_away(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("accounts:login"))

        self.assertEqual(response.status_code, 302)

    def test_session_key_rotates_on_login(self):
        self.client.get(reverse("accounts:login"))
        before = self.client.session.session_key

        self.client.post(
            reverse("accounts:login"),
            {"username": "alice", "password": "correct-horse-42"},
        )

        # Reusing the pre-login session id would allow session fixation.
        self.assertNotEqual(before, self.client.session.session_key)


class LogoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            "alice", email="alice@example.com", password="correct-horse-42"
        )

    def test_logout_rejects_get(self):
        # POST-only since Django 5.0: a GET logout can be fired by a
        # prefetch, a link scanner or an <img> tag.
        self.client.force_login(self.user)

        response = self.client.get(reverse("accounts:logout"))

        self.assertEqual(response.status_code, 405)

    def test_logout_via_post_signs_the_user_out(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("accounts:logout"), follow=True)

        self.assertFalse(response.context["user"].is_authenticated)


class SignUpTests(TestCase):
    def _data(self, **overrides):
        defaults = {
            "username": "alice",
            "email": "alice@example.com",
            "password1": "correct-horse-42",
            "password2": "correct-horse-42",
        }
        return {**defaults, **overrides}

    def test_signup_creates_an_inactive_user_and_does_not_sign_them_in(self):
        """Changed in phase 16. This used to sign the user straight in.

        Known issue 16: that let anyone register an address they did not
        control. The quiet danger is not the unwanted account, it is that
        password reset then becomes a takeover in reverse -- the real owner
        of the address clicks "forgot password" and inherits whatever the
        impostor put in the account.
        """
        response = self.client.post(reverse("accounts:signup"), self._data(), follow=True)

        user = User.objects.get(username="alice")
        self.assertFalse(user.is_active)
        self.assertFalse(response.context["user"].is_authenticated)

    def test_signup_creates_self_participant(self):
        from expenses.models import Participant

        self.client.post(reverse("accounts:signup"), self._data())
        user = User.objects.get(username="alice")
        self.assertTrue(
            Participant.objects.filter(user=user, is_self=True, name="alice (self)").exists()
        )

    def test_signup_sends_one_confirmation_email(self):
        self.client.post(reverse("accounts:signup"), self._data())

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Confirm", mail.outbox[0].subject)

    def test_following_the_link_activates_and_signs_in(self):
        self.client.post(reverse("accounts:signup"), self._data())
        link = re.search(r"(/accounts/verify/[^/\s]+/[^/\s]+/)", mail.outbox[0].body).group(1)

        response = self.client.get(link, follow=True)

        self.assertTrue(User.objects.get(username="alice").is_active)
        self.assertTrue(response.context["user"].is_authenticated)

    def test_the_link_is_single_use(self):
        # The token hash includes is_active, so activating the account
        # invalidates every outstanding link without storing anything.
        self.client.post(reverse("accounts:signup"), self._data())
        link = re.search(r"(/accounts/verify/[^/\s]+/[^/\s]+/)", mail.outbox[0].body).group(1)
        self.client.get(link)
        self.client.logout()

        response = self.client.get(link, follow=True)

        self.assertFalse(response.context["user"].is_authenticated)

    def test_a_tampered_token_is_refused(self):
        self.client.post(reverse("accounts:signup"), self._data())
        link = re.search(r"(/accounts/verify/[^/\s]+/[^/\s]+/)", mail.outbox[0].body).group(1)

        response = self.client.get(link[:-3] + "xx/", follow=True)

        self.assertFalse(User.objects.get(username="alice").is_active)
        self.assertFalse(response.context["user"].is_authenticated)

    def test_an_unverified_user_cannot_sign_in(self):
        self.client.post(reverse("accounts:signup"), self._data())

        response = self.client.post(
            reverse("accounts:login"),
            {"username": "alice", "password": "correct-horse-42"},
        )

        # is_active=False is refused by ModelBackend, so no extra check is
        # needed on the login view.
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["user"].is_authenticated)

    def test_password_is_hashed_not_stored_in_clear_text(self):
        self.client.post(reverse("accounts:signup"), self._data())

        user = User.objects.get(username="alice")

        self.assertNotEqual(user.password, "correct-horse-42")
        self.assertTrue(user.check_password("correct-horse-42"))

    def test_email_is_normalised_to_lowercase(self):
        # Otherwise Alice@example.com and alice@example.com become two
        # accounts, which the unique constraint would happily allow.
        self.client.post(reverse("accounts:signup"), self._data(email="Alice@Example.com"))

        self.assertEqual(User.objects.get(username="alice").email, "alice@example.com")

    def test_duplicate_email_is_a_field_error(self):
        User.objects.create_user("bob", email="alice@example.com", password="pw12345!")

        response = self.client.post(reverse("accounts:signup"), self._data())

        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)

    def test_duplicate_check_matches_a_mixed_case_address_already_in_the_db(self):
        # The stored address must be mixed case for this to mean anything.
        # clean_email lowercases the *incoming* value, so if the existing row
        # were already lowercase, __iexact and = would behave identically and
        # the test would pass even with the lookup broken.
        #
        # Rows like this arise from createsuperuser and the admin, neither of
        # which goes through SignUpForm.
        User.objects.create_user("bob", email="Alice@Example.com", password="pw12345!")

        response = self.client.post(reverse("accounts:signup"), self._data())

        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="alice").exists())

    def test_mismatched_passwords_are_rejected(self):
        response = self.client.post(
            reverse("accounts:signup"), self._data(password2="something-else")
        )

        self.assertIn("password2", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="alice").exists())

    def test_weak_password_is_rejected(self):
        # AUTH_PASSWORD_VALIDATORS are inherited from UserCreationForm; a
        # hand-rolled form would silently lose them.
        response = self.client.post(
            reverse("accounts:signup"), self._data(password1="password", password2="password")
        )

        self.assertIn("password2", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="alice").exists())

    def test_authenticated_user_is_redirected_away_from_signup(self):
        existing = User.objects.create_user(
            "bob", email="bob@example.com", password="correct-horse-42"
        )
        self.client.force_login(existing)

        response = self.client.get(reverse("accounts:signup"))

        self.assertRedirects(response, reverse("expenses:expense_list"))

    def test_signup_uses_the_custom_user_model(self):
        # UserCreationForm's own Meta points at django.contrib.auth's User,
        # so failing to override it writes to the wrong table.
        self.client.post(reverse("accounts:signup"), self._data())

        self.assertEqual(User.objects.get(username="alice")._meta.label, "accounts.User")


class PasswordResetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            "alice", email="alice@example.com", password="correct-horse-42"
        )

    def _request_reset(self, email="alice@example.com"):
        mail.outbox = []
        response = self.client.post(reverse("accounts:password_reset"), {"email": email})
        return response

    def _link_from_email(self):
        return re.search(r"(/accounts/password/reset/[^/\s]+/[^/\s]+/)", mail.outbox[0].body).group(
            1
        )

    def test_reset_request_sends_one_email(self):
        self._request_reset()

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("alice@example.com", mail.outbox[0].to)

    def test_unknown_email_looks_identical_and_sends_nothing(self):
        # The response must not reveal whether the address has an account,
        # or the form becomes an account-enumeration oracle.
        known = self._request_reset("alice@example.com")
        known_url = known.url

        unknown = self._request_reset("nobody@example.com")

        self.assertEqual(unknown.status_code, known.status_code)
        self.assertEqual(unknown.url, known_url)
        self.assertEqual(len(mail.outbox), 0)

    def test_emailed_link_allows_setting_a_new_password(self):
        self._request_reset()
        link = self._link_from_email()

        response = self.client.get(link, follow=True)
        self.assertTrue(response.context["validlink"])

        final_url = response.redirect_chain[-1][0]
        self.client.post(
            final_url,
            {"new_password1": "brand-new-pass-99", "new_password2": "brand-new-pass-99"},
        )

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("brand-new-pass-99"))

    def test_old_password_stops_working_after_reset(self):
        self._request_reset()
        link = self._link_from_email()
        final_url = self.client.get(link, follow=True).redirect_chain[-1][0]
        self.client.post(
            final_url,
            {"new_password1": "brand-new-pass-99", "new_password2": "brand-new-pass-99"},
        )

        self.assertFalse(self.client.login(username="alice", password="correct-horse-42"))

    def test_reset_token_is_single_use(self):
        self._request_reset()
        link = self._link_from_email()
        final_url = self.client.get(link, follow=True).redirect_chain[-1][0]
        self.client.post(
            final_url,
            {"new_password1": "brand-new-pass-99", "new_password2": "brand-new-pass-99"},
        )

        # The token is derived from the password hash, so changing the
        # password invalidates it.
        response = self.client.get(link, follow=True)

        self.assertFalse(response.context["validlink"])

    def test_tampered_token_is_refused(self):
        self._request_reset()
        link = self._link_from_email()
        uidb64, token = link.rstrip("/").split("/")[-2:]

        response = self.client.get(
            reverse(
                "accounts:password_reset_confirm",
                kwargs={"uidb64": uidb64, "token": token[:-4] + "aaaa"},
            ),
            follow=True,
        )

        self.assertFalse(response.context["validlink"])


class PasswordChangeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            "alice", email="alice@example.com", password="correct-horse-42"
        )

    def test_password_change_requires_login(self):
        response = self.client.get(reverse("accounts:password_change"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_current_password_is_required(self):
        # Without this check an unattended signed-in session could be used
        # to lock the real owner out.
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": "wrong",
                "new_password1": "brand-new-pass-99",
                "new_password2": "brand-new-pass-99",
            },
        )

        self.assertIn("old_password", response.context["form"].errors)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("correct-horse-42"))

    def test_password_change_succeeds_and_keeps_the_session(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": "correct-horse-42",
                "new_password1": "brand-new-pass-99",
                "new_password2": "brand-new-pass-99",
            },
            follow=True,
        )

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("brand-new-pass-99"))
        # Django rotates the session auth hash rather than logging the user
        # out, so the session survives its own password change.
        self.assertTrue(response.context["user"].is_authenticated)
