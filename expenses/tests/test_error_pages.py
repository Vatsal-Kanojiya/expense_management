"""Error pages and the production security settings.

Error templates only render when DEBUG is False, so they are the classic
thing that works locally and 500s in production.
"""

import os
import subprocess
import sys
from pathlib import Path

from django.template.loader import get_template
from django.template.loader_tags import ExtendsNode
from django.test import SimpleTestCase, override_settings

BASE_DIR = Path(__file__).resolve().parent.parent.parent


@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
class ErrorPageTests(SimpleTestCase):
    def test_404_renders_the_custom_template(self):
        self.assertContains(self.client.get("/no-such-page/"), "Not found", status_code=404)

    def test_404_does_not_explain_why(self):
        # Saying "this belongs to another user" would leak exactly what the
        # scoped querysets exist to hide.
        body = self.client.get("/expenses/99999/edit/").content.decode()

        for leak in ("another user", "belongs to", "permission"):
            self.assertNotIn(leak, body.lower())

    def test_500_template_does_not_extend_anything(self):
        # Asserted against the *compiled* nodelist, not the file's text: the
        # template documents this very rule in a comment that names the tags
        # a text search would look for.
        nodes = get_template("500.html").template.nodelist

        self.assertFalse(any(isinstance(node, ExtendsNode) for node in nodes))

    def test_500_template_renders_with_an_empty_context(self):
        # The failure this guards against: a 500 page that itself raises
        # turns one handled error into an unhandled one with no page at all.
        # Django renders 500.html with no context and no context processors.
        self.assertIn("Something went wrong", get_template("500.html").render({}))


class DeploySettingsTests(SimpleTestCase):
    """The deploy checks are gated on DEBUG at import time.

    ``override_settings`` cannot help here: the ``if not DEBUG`` block in
    settings.py has already run by the time any test executes. The only
    honest way to assert the production configuration is to start a fresh
    process without DEBUG, which is also exactly what CI does.
    """

    def _check_deploy(self, debug):
        env = {**os.environ, "DEBUG": debug, "ALLOWED_HOSTS": "example.com"}
        # CI sets this to False for the test job so the SSL redirect does not
        # 301 every test client request. Inheriting it here would have this
        # test assert the production config is clean while measuring the
        # relaxed one, which is the exact hole it exists to close.
        env.pop("SECURE_SSL_REDIRECT", None)

        return subprocess.run(
            [sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"],
            cwd=BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_production_config_passes_the_deploy_check(self):
        result = self._check_deploy("False")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_development_config_deliberately_does_not(self):
        # Not a bug. Secure cookies are not sent over plain HTTP and an SSL
        # redirect makes http://localhost unreachable, so local development
        # must fail these checks.
        self.assertNotEqual(self._check_deploy("True").returncode, 0)
