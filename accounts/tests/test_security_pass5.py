"""Security pass 5 (HANDOVER.md): errors, logs, the admin site, deletion.

Each checklist item is its own section below, in HANDOVER.md's order.
Several items were already correctly implemented; those sections pin the
existing behaviour rather than changing it, and say so.
"""

import logging
from unittest import mock

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.debug import SafeExceptionReporterFilter
from rest_framework_simplejwt.tokens import RefreshToken

from accounts import admin as accounts_admin
from accounts.deletion import delete_account
from expenses import admin as expenses_admin
from expenses.models import Category

User = get_user_model()
PASSWORD = "Str0ng-Enough-Pass"
SECRET = "th3-s3cr3t-Passw0rd-XYZ"


def api_url(name):
    return reverse(f"api:v1:{name}")


def _innermost_frame_in(exc, filename_fragment):
    """The deepest traceback frame whose file matches, from a raised exc.

    Walking from the outside in: the innermost match is the one that was
    actually executing (a decorated view can call another decorated
    function; the innermost is the one whose locals we want to check).
    """
    frame = None
    tb = exc.__traceback__
    while tb is not None:
        if filename_fragment in tb.tb_frame.f_code.co_filename:
            frame = tb.tb_frame
        tb = tb.tb_next
    return frame


def _cleansed_locals(frame):
    """What an admin's error mail or a DEBUG=True page would show for frame.

    SafeExceptionReporterFilter is the actual class Django uses for both:
    LOGGING's mail_admins handler (AdminEmailHandler) and the on-screen
    technical_500 page run every frame's locals through it. is_active()
    only engages with DEBUG=False, which is production's setting.
    """
    with override_settings(DEBUG=False):
        return dict(SafeExceptionReporterFilter().get_traceback_frame_variables(None, frame))


CLEANSED = SafeExceptionReporterFilter.cleansed_substitute


# --- Item 1: errors reveal nothing but a plain message and a request id ----


class ErrorPageRequestIdTests(TestCase):
    """404 and 500 show a request id, and only that -- never a traceback,
    file path, setting or query."""

    @override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
    def test_404_shows_the_request_id_that_the_response_header_carries(self):
        response = self.client.get("/no-such-page/")

        self.assertEqual(response.status_code, 404)
        request_id = response["X-Request-ID"]
        self.assertTrue(request_id)
        self.assertContains(response, request_id, status_code=404)

    @override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
    def test_500_shows_the_request_id_that_the_response_header_carries(self):
        alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        client = Client(raise_request_exception=False)
        client.force_login(alice)

        with mock.patch(
            "expenses.views.DashboardView.get_context_data",
            side_effect=RuntimeError("kaboom, and SECRET_KEY=should-never-appear"),
        ):
            response = client.get("/")

        self.assertEqual(response.status_code, 500)
        request_id = response["X-Request-ID"]
        self.assertTrue(request_id)
        body = response.content.decode()
        self.assertIn(request_id, body)
        self.assertIn("Something went wrong", body)
        # No stack trace, setting or SQL -- the custom handler500
        # (config/views.py) renders 500.html with nothing but the id, so
        # there is structurally nothing else it could show.
        for leak in ("Traceback", "SECRET_KEY", "SELECT ", "kaboom"):
            self.assertNotIn(leak, body)

    @override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
    def test_an_unhandled_api_error_is_the_plain_500_page_not_json(self):
        alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        client = Client(raise_request_exception=False)
        client.force_login(alice)

        with mock.patch(
            "accounts.api.MeView.get", side_effect=RuntimeError("boom, path=/etc/passwd")
        ):
            response = client.get(api_url("me"))

        self.assertEqual(response.status_code, 500)
        self.assertNotIn("application/json", response["Content-Type"])
        request_id = response["X-Request-ID"]
        self.assertTrue(request_id)
        body = response.content.decode()
        self.assertIn(request_id, body)
        for leak in ("Traceback", "boom", "/etc/passwd", "SELECT "):
            self.assertNotIn(leak, body)

    def test_handler500_is_the_request_id_aware_view(self):
        from config.urls import handler500

        self.assertEqual(handler500, "config.views.server_error")

    def test_the_view_reads_the_contextvar_not_the_request(self):
        # config/views.py's whole point: no context processors, no
        # ``request`` attribute lookup, so a broken one of those cannot
        # turn a handled 500 into an unhandled one. render({}) -- what
        # Django's own default view does -- must still succeed.
        from django.template.loader import get_template

        self.assertIn("Something went wrong", get_template("500.html").render({}))


# --- Item 2: secrets never reach a log line or an error report -------------


class NoSecretsInApplicationLogLinesTests(TestCase):
    """The lines this app writes itself (not Django's own machinery)."""

    def test_a_failed_web_login_does_not_log_the_password(self):
        User.objects.create_user("alice", "alice@example.com", PASSWORD)

        with self.assertLogs("django.security", level="WARNING") as logs:
            self.client.post(
                reverse("accounts:login"), {"username": "alice", "password": "guess-me-not"}
            )

        self.assertNotIn("guess-me-not", "\n".join(logs.output))

    def test_a_failed_api_login_does_not_log_the_password(self):
        User.objects.create_user("alice", "alice@example.com", PASSWORD)

        with self.assertLogs("django.security", level="WARNING") as logs:
            self.client.post(
                api_url("auth-login"),
                {"username": "alice", "password": "guess-me-not"},
                content_type="application/json",
            )

        self.assertNotIn("guess-me-not", "\n".join(logs.output))

    def test_account_deletion_log_line_names_no_secret(self):
        alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        refresh = RefreshToken.for_user(alice)

        with self.assertLogs("expenses", level="INFO") as logs:
            delete_account(alice)

        joined = "\n".join(logs.output)
        self.assertNotIn(PASSWORD, joined)
        self.assertNotIn(str(refresh), joined)


class SensitiveVariablesAreMaskedTests(TestCase):
    """@sensitive_variables() on accounts/api.py's views (security pass 5).

    Each test raises an exception from inside the real view, past the
    point where it has bound the password or token to a local variable,
    and checks what SafeExceptionReporterFilter -- the filter behind both
    the DEBUG=True error page and LOGGING's mail_admins handler -- would
    show for that frame. Without the decorator this fails: the local
    comes back with its real value, not the starred-out placeholder.
    """

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def _raise(self, callable_):
        # Not self.assertRaises(): its context manager deliberately clears
        # exc_value.__traceback__ (unittest.case, to avoid a reference
        # cycle) before handing the exception back, which is exactly the
        # frame chain this needs.
        try:
            callable_()
        except RuntimeError as exc:
            return exc
        raise AssertionError("expected a RuntimeError")

    def test_login_masks_the_password_local(self):
        with mock.patch("accounts.api.django_authenticate", side_effect=RuntimeError("boom")):
            exc = self._raise(
                lambda: self.client.post(
                    api_url("auth-login"),
                    {"username": "alice", "password": SECRET},
                    content_type="application/json",
                )
            )

        frame = _innermost_frame_in(exc, "accounts/api.py")
        cleansed = _cleansed_locals(frame)

        self.assertEqual(cleansed.get("password"), CLEANSED)
        self.assertNotIn(SECRET, repr(cleansed))

    def test_signup_masks_the_password_in_the_validated_data(self):
        with mock.patch("accounts.api.send_verification_email", side_effect=RuntimeError("boom")):
            exc = self._raise(
                lambda: self.client.post(
                    api_url("auth-signup"),
                    {
                        "username": "newperson",
                        "email": "newperson@example.com",
                        "password": SECRET,
                        "password_confirm": SECRET,
                    },
                    content_type="application/json",
                )
            )

        frame = _innermost_frame_in(exc, "accounts/api.py")
        cleansed = _cleansed_locals(frame)

        # A bare @sensitive_variables() cleanses every local in the frame,
        # including the "data" dict that held the raw password under the
        # "password" and "password_confirm" keys.
        self.assertEqual(cleansed.get("data"), CLEANSED)
        self.assertNotIn(SECRET, repr(cleansed))

    def test_password_change_masks_the_new_password(self):
        self.client.force_login(self.alice)

        with mock.patch("accounts.api.revoke_refresh_tokens", side_effect=RuntimeError("boom")):
            exc = self._raise(
                lambda: self.client.post(
                    api_url("auth-password-change"),
                    {
                        "old_password": PASSWORD,
                        "new_password": SECRET,
                        "new_password_confirm": SECRET,
                    },
                    content_type="application/json",
                )
            )

        frame = _innermost_frame_in(exc, "accounts/api.py")
        cleansed = _cleansed_locals(frame)

        self.assertEqual(cleansed.get("data"), CLEANSED)
        self.assertNotIn(SECRET, repr(cleansed))

    def test_password_reset_confirm_masks_the_new_password(self):
        uid = urlsafe_base64_encode(force_bytes(self.alice.pk))
        token = default_token_generator.make_token(self.alice)

        with mock.patch("accounts.api.revoke_refresh_tokens", side_effect=RuntimeError("boom")):
            exc = self._raise(
                lambda: self.client.post(
                    api_url("auth-password-reset-confirm"),
                    {
                        "uid": uid,
                        "token": token,
                        "new_password": SECRET,
                        "new_password_confirm": SECRET,
                    },
                    content_type="application/json",
                )
            )

        frame = _innermost_frame_in(exc, "accounts/api.py")
        cleansed = _cleansed_locals(frame)

        self.assertEqual(cleansed.get("data"), CLEANSED)
        self.assertNotIn(SECRET, repr(cleansed))

    def test_logout_masks_the_refresh_token(self):
        refresh = RefreshToken.for_user(self.alice)

        with mock.patch("accounts.api.RefreshToken.blacklist", side_effect=RuntimeError("boom")):
            exc = self._raise(
                lambda: self.client.post(
                    api_url("auth-logout"),
                    {"refresh": str(refresh)},
                    content_type="application/json",
                )
            )

        frame = _innermost_frame_in(exc, "accounts/api.py")
        cleansed = _cleansed_locals(frame)

        self.assertEqual(cleansed.get("body"), CLEANSED)
        self.assertNotIn(str(refresh), repr(cleansed))

    def test_every_password_or_token_view_carries_the_decorator(self):
        # A structural check for the views a live exception is awkward to
        # provoke (RefreshView delegates to a third-party base class), so
        # every one of them is covered at least this way.
        from accounts.api import (
            LoginView,
            LogoutView,
            PasswordChangeView,
            PasswordResetConfirmView,
            RefreshView,
            SignupView,
            VerifyEmailView,
        )

        for view in (
            SignupView,
            VerifyEmailView,
            LoginView,
            RefreshView,
            LogoutView,
            PasswordChangeView,
            PasswordResetConfirmView,
        ):
            with self.subTest(view=view.__name__):
                self.assertTrue(
                    hasattr(view.post, "__wrapped__"),
                    f"{view.__name__}.post is missing @sensitive_variables()",
                )


class AdminErrorMailIsFilteredTests(TestCase):
    """End to end: LOGGING's mail_admins handler, with ADMINS configured."""

    @override_settings(
        DEBUG=False, ADMINS=[("Admin", "admin@example.com")], ALLOWED_HOSTS=["testserver"]
    )
    def test_a_login_crash_mails_admins_without_the_password(self):
        User.objects.create_user("alice", "alice@example.com", PASSWORD)
        mail.outbox = []
        client = Client(raise_request_exception=False)

        with mock.patch("accounts.api.django_authenticate", side_effect=RuntimeError("boom")):
            response = client.post(
                api_url("auth-login"),
                {"username": "alice", "password": SECRET},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn(SECRET, mail.outbox[0].body)

    @override_settings(DEBUG=False, ADMINS=[], ALLOWED_HOSTS=["testserver"])
    def test_no_admins_means_no_mail_at_all(self):
        # The fail-safe default (config/settings.py): nothing is sent
        # until an operator deliberately sets ADMINS.
        User.objects.create_user("alice", "alice@example.com", PASSWORD)
        mail.outbox = []
        client = Client(raise_request_exception=False)

        with mock.patch("accounts.api.django_authenticate", side_effect=RuntimeError("boom")):
            client.post(
                api_url("auth-login"),
                {"username": "alice", "password": SECRET},
                content_type="application/json",
            )

        self.assertEqual(len(mail.outbox), 0)


class _CollectingHandler(logging.Handler):
    """Like assertLogs, but does not require at least one record.

    Nothing here is expected to log a session id or an Authorization
    header at all -- that is the point being pinned -- and assertLogs
    fails outright when nothing was logged, so a plain handler collects
    whatever comes (zero lines or many) without that assumption.
    """

    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))


class NoSessionIdOrHeaderInLogsTests(TestCase):
    """Session ids and the Authorization/Cookie headers stay out of logs."""

    def _captured(self, callable_):
        handler = _CollectingHandler()
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            callable_()
        finally:
            root.removeHandler(handler)
        return "\n".join(handler.lines)

    def test_logging_in_and_out_never_logs_the_session_key(self):
        User.objects.create_user("alice", "alice@example.com", PASSWORD)

        def _flow():
            self.client.post(reverse("accounts:login"), {"username": "alice", "password": PASSWORD})
            self.session_key = self.client.session.session_key
            self.client.get(reverse("expenses:dashboard"))
            self.client.post(reverse("accounts:logout"))

        output = self._captured(_flow)

        self.assertIsNotNone(self.session_key)
        self.assertNotIn(self.session_key, output)

    def test_the_authorization_header_is_never_logged(self):
        alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        refresh = RefreshToken.for_user(alice)
        access = str(refresh.access_token)

        output = self._captured(
            lambda: self.client.get(api_url("me"), HTTP_AUTHORIZATION=f"Bearer {access}")
        )

        self.assertNotIn(access, output)


# --- Item 3: the admin site --------------------------------------------------


class AdminListPagesHideSecretsTests(TestCase):
    """Already correct: no ModelAdmin's list_display names a password or a
    raw token. Pinned rather than fixed."""

    def test_user_admin_list_display_has_no_password_field(self):
        self.assertNotIn("password", accounts_admin.UserAdmin.list_display)

    def test_no_registered_admin_shows_a_raw_token_or_password_column(self):
        leaky = {"password", "password1", "password2", "token", "refresh", "access"}
        for model, model_admin in admin_site_registry().items():
            with self.subTest(model=model.__name__):
                self.assertFalse(leaky & set(model_admin.list_display))


def admin_site_registry():
    from django.contrib import admin

    return dict(admin.site._registry)


class AdminChangesAreLoggedTests(TestCase):
    """Django's own LogEntry, already wired in because nothing here
    overrides save_model/delete_model/log_addition. Pinned."""

    def setUp(self):
        # A superuser, not merely is_staff: pass 3 already pins that
        # is_staff alone grants no model permission, so a plain staff
        # account cannot add or delete anything here to log in the first
        # place. This section is about LogEntry, not about permissions.
        self.staff = User.objects.create_superuser("staffer", "staffer@example.com", PASSWORD)

    def test_adding_a_category_through_the_admin_writes_a_log_entry(self):
        self.client.force_login(self.staff)
        before = LogEntry.objects.count()

        response = self.client.post(
            "/admin/expenses/category/add/",
            {"name": "Utilities", "user": self.staff.pk},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(LogEntry.objects.count(), before + 1)
        entry = LogEntry.objects.latest("action_time")
        self.assertEqual(entry.user_id, self.staff.pk)
        self.assertEqual(entry.object_repr, "Utilities")

    def test_deleting_a_category_through_the_admin_writes_a_log_entry(self):
        self.client.force_login(self.staff)
        category = Category.objects.create(user=self.staff, name="Temp")
        before = LogEntry.objects.count()

        self.client.post(
            "/admin/expenses/category/",
            {
                "action": "delete_selected",
                "_selected_action": [str(category.pk)],
                "post": "yes",
            },
        )

        self.assertFalse(Category.objects.filter(pk=category.pk).exists())
        self.assertEqual(LogEntry.objects.count(), before + 1)

    def test_staff_can_reach_the_admin_and_see_the_registered_models(self):
        self.client.force_login(self.staff)

        response = self.client.get("/admin/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Categories")
        self.assertContains(response, "Users")


del expenses_admin  # imported only so app-loading errors surface here
