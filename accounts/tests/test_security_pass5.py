"""Security pass 5 (HANDOVER.md): errors, logs, the admin site, deletion.

Each checklist item is its own section below, in HANDOVER.md's order.
Several items were already correctly implemented; those sections pin the
existing behaviour rather than changing it, and say so.
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

User = get_user_model()
PASSWORD = "Str0ng-Enough-Pass"


def api_url(name):
    return reverse(f"api:v1:{name}")


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
