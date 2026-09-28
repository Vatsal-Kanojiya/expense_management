"""Roadmap A1: an unverified account must not squat an email or username.

"Unverified" means exactly is_active=False AND email_verified_at IS NULL.
Sign-up (web and API) treats such an account as if it were not there, and
deletes it -- through accounts.deletion.delete_account, in one transaction
-- the moment a fresh sign-up replaces it.
"""

import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.deletion import delete_account

User = get_user_model()


def url(name):
    return reverse(f"api:v1:{name}")


class SignUpFormSquattingTests(TestCase):
    """The web form (accounts/forms.py's SignUpForm)."""

    def _data(self, **overrides):
        defaults = {
            "username": "alice",
            "email": "alice@example.com",
            "password1": "correct-horse-42",
            "password2": "correct-horse-42",
        }
        return {**defaults, **overrides}

    def test_a_pending_signup_does_not_block_a_fresh_one_for_the_same_email(self):
        User.objects.create_user(
            "impostor", email="alice@example.com", password="whatever-1", is_active=False
        )

        response = self.client.post(reverse("accounts:signup"), self._data(), follow=True)

        self.assertTrue(User.objects.filter(username="alice", email="alice@example.com").exists())
        self.assertFalse(User.objects.filter(username="impostor").exists())
        self.assertTemplateUsed(response, "registration/verify_email_sent.html")

    def test_a_pending_signup_does_not_block_a_fresh_one_for_the_same_username(self):
        User.objects.create_user(
            "alice", email="impostor@example.com", password="whatever-1", is_active=False
        )

        self.client.post(reverse("accounts:signup"), self._data())

        user = User.objects.get(username="alice")
        self.assertEqual(user.email, "alice@example.com")
        self.assertFalse(User.objects.filter(email="impostor@example.com").exists())

    def test_the_old_pending_account_is_really_gone(self):
        squatter = User.objects.create_user(
            "impostor", email="alice@example.com", password="whatever-1", is_active=False
        )

        self.client.post(reverse("accounts:signup"), self._data())

        self.assertFalse(User.objects.filter(pk=squatter.pk).exists())

    def test_a_verified_then_deactivated_account_still_blocks(self):
        # An admin deactivating a real, verified account must not turn it
        # into something a stranger's sign-up can bulldoze.
        User.objects.create_user(
            "alice",
            email="alice@example.com",
            password="whatever-1",
            is_active=False,
            email_verified_at=timezone.now(),
        )

        response = self.client.post(reverse("accounts:signup"), self._data())

        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.assertEqual(User.objects.filter(email="alice@example.com").count(), 1)

    def test_an_active_account_still_blocks(self):
        User.objects.create_user("alice", email="alice@example.com", password="whatever-1")

        response = self.client.post(reverse("accounts:signup"), self._data())

        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)

    def test_username_still_blocks_when_held_by_an_active_account(self):
        User.objects.create_user("alice", email="someone-else@example.com", password="w-1")

        response = self.client.post(reverse("accounts:signup"), self._data())

        self.assertEqual(response.status_code, 200)
        self.assertIn("username", response.context["form"].errors)

    def test_replacing_a_squatter_is_atomic_with_creating_the_new_account(self):
        # A weak-password submission must not have already deleted the
        # squatter -- the whole thing is one transaction, or the address
        # is left held by nobody until the next attempt succeeds.
        squatter = User.objects.create_user(
            "impostor", email="alice@example.com", password="whatever-1", is_active=False
        )

        self.client.post(
            reverse("accounts:signup"),
            self._data(password1="short", password2="short"),
        )

        self.assertTrue(User.objects.filter(pk=squatter.pk).exists())


class SignupApiSquattingTests(TestCase):
    """The same rule over the API (accounts/api.py's SignupView)."""

    payload = {
        "username": "bella",
        "email": "bella@example.com",
        "password": "Str0ng-Enough-Pass",
        "password_confirm": "Str0ng-Enough-Pass",
    }

    def post(self, name, data):
        return self.client.post(url(name), data, content_type="application/json")

    def test_a_pending_signup_does_not_block_a_fresh_one(self):
        squatter = User.objects.create_user(
            "impostor", email="bella@example.com", password="whatever-1", is_active=False
        )

        response = self.post("auth-signup", self.payload)

        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(username="bella").exists())
        self.assertFalse(User.objects.filter(pk=squatter.pk).exists())

    def test_a_verified_then_deactivated_account_still_blocks(self):
        User.objects.create_user(
            "bella",
            email="bella@example.com",
            password="whatever-1",
            is_active=False,
            email_verified_at=timezone.now(),
        )

        response = self.post("auth-signup", self.payload)

        self.assertEqual(response.status_code, 400)


class EmailVerifiedAtTests(TestCase):
    """Verification sets the field; only is_active=False + null counts as unverified."""

    def test_verifying_through_the_web_sets_email_verified_at(self):
        self.client.post(
            reverse("accounts:signup"),
            {
                "username": "carol",
                "email": "carol@example.com",
                "password1": "correct-horse-42",
                "password2": "correct-horse-42",
            },
        )
        link = re.search(r"(/accounts/verify/[^/\s]+/[^/\s]+/)", mail.outbox[0].body).group(1)

        self.client.get(link)

        user = User.objects.get(username="carol")
        self.assertIsNotNone(user.email_verified_at)

    def test_verifying_through_the_api_sets_email_verified_at(self):
        self.client.post(
            url("auth-signup"),
            {
                "username": "dave",
                "email": "dave@example.com",
                "password": "Str0ng-Enough-Pass",
                "password_confirm": "Str0ng-Enough-Pass",
            },
            content_type="application/json",
        )
        match = re.search(r"/verify-email/([^/\s]+)/([^/\s]+)", mail.outbox[0].body)

        self.client.post(
            url("auth-verify-email"),
            {"uid": match.group(1), "token": match.group(2)},
            content_type="application/json",
        )

        user = User.objects.get(username="dave")
        self.assertIsNotNone(user.email_verified_at)

    def test_a_freshly_created_active_user_has_no_email_verified_at(self):
        # createsuperuser / the admin creating an active account directly:
        # never went through a link, and that is fine -- it is active, so
        # it is never "unverified" regardless of this field.
        user = User.objects.create_superuser(
            "admin", email="admin@example.com", password="whatever-1"
        )

        self.assertIsNone(user.email_verified_at)
        self.assertTrue(user.is_active)


class PurgeUnverifiedCommandTests(TestCase):
    def test_purge_removes_only_old_unverified_accounts(self):
        old_unverified = User.objects.create_user(
            "old_unverified", email="old@example.com", password="w-1", is_active=False
        )
        User.objects.filter(pk=old_unverified.pk).update(
            date_joined=timezone.now() - timezone.timedelta(days=10)
        )

        recent_unverified = User.objects.create_user(
            "recent_unverified", email="recent@example.com", password="w-1", is_active=False
        )

        old_verified = User.objects.create_user(
            "old_verified",
            email="verified@example.com",
            password="w-1",
            email_verified_at=timezone.now(),
        )
        User.objects.filter(pk=old_verified.pk).update(
            date_joined=timezone.now() - timezone.timedelta(days=10)
        )

        old_deactivated_verified = User.objects.create_user(
            "old_deactivated",
            email="deactivated@example.com",
            password="w-1",
            is_active=False,
            email_verified_at=timezone.now(),
        )
        User.objects.filter(pk=old_deactivated_verified.pk).update(
            date_joined=timezone.now() - timezone.timedelta(days=10)
        )

        from django.core.management import call_command

        call_command("purge_unverified", days=7)

        self.assertFalse(User.objects.filter(pk=old_unverified.pk).exists())
        self.assertTrue(User.objects.filter(pk=recent_unverified.pk).exists())
        self.assertTrue(User.objects.filter(pk=old_verified.pk).exists())
        self.assertTrue(User.objects.filter(pk=old_deactivated_verified.pk).exists())

    def test_dry_run_removes_nothing(self):
        old_unverified = User.objects.create_user(
            "old_unverified", email="old@example.com", password="w-1", is_active=False
        )
        User.objects.filter(pk=old_unverified.pk).update(
            date_joined=timezone.now() - timezone.timedelta(days=10)
        )

        from django.core.management import call_command

        call_command("purge_unverified", days=7, dry_run=True)

        self.assertTrue(User.objects.filter(pk=old_unverified.pk).exists())


class DeleteAccountRequestTests(TestCase):
    def test_delete_account_accepts_an_optional_request(self):
        user = User.objects.create_user("erin", email="erin@example.com", password="w-1")

        counts = delete_account(user)

        self.assertFalse(User.objects.filter(pk=user.pk).exists())
        self.assertIn("expenses", counts)
