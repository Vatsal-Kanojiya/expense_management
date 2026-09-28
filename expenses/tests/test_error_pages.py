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

    def _check_deploy(self, debug, **overrides):
        env = {**os.environ, "DEBUG": debug, "ALLOWED_HOSTS": "example.com"}
        # CI sets this to False for the test job so the SSL redirect does not
        # 301 every test client request. Inheriting it here would have this
        # test assert the production config is clean while measuring the
        # relaxed one, which is the exact hole it exists to close.
        #
        # The cookie flags are popped for the same reason: compose.yaml turns
        # them off, and `make test` runs inside that environment.
        for relaxed in ("SECURE_SSL_REDIRECT", "SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE"):
            env.pop(relaxed, None)
        env.update(overrides)

        return subprocess.run(
            [sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"],
            cwd=BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_production_config_passes_the_deploy_check(self):
        # A shared cache, as compose.yaml sets: the check only reads the
        # backend's name, so nothing needs to be listening on that address.
        result = self._check_deploy("False", CACHE_URL="rediscache://127.0.0.1:6379/2")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_development_config_deliberately_does_not(self):
        # Not a bug. Secure cookies are not sent over plain HTTP and an SSL
        # redirect makes http://localhost unreachable, so local development
        # must fail these checks.
        self.assertNotEqual(self._check_deploy("True").returncode, 0)

    def test_relaxed_cookies_fail_the_deploy_check(self):
        # The local compose stack serves plain HTTP and turns these off. The
        # switch must be loud anywhere else: CI's deploy job never sets it,
        # and this proves that if something did, the build would go red.
        result = self._check_deploy(
            "False", SESSION_COOKIE_SECURE="False", CSRF_COOKIE_SECURE="False"
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("security.W012", result.stdout + result.stderr)
        self.assertIn("security.W016", result.stdout + result.stderr)

    def _cookie_names(self, debug, **overrides):
        # Same fresh-process reasoning as _check_deploy: SESSION_COOKIE_NAME
        # and CSRF_COOKIE_NAME are set inside the same DEBUG-gated block at
        # import time, so override_settings cannot see what they would be.
        env = {**os.environ, "DEBUG": debug, "ALLOWED_HOSTS": "example.com"}
        for relaxed in ("SECURE_SSL_REDIRECT", "SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE"):
            env.pop(relaxed, None)
        env.update(overrides)

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import django; django.setup(); "
                "from django.conf import settings; "
                "print(settings.SESSION_COOKIE_NAME); "
                "print(settings.CSRF_COOKIE_NAME)",
            ],
            cwd=BASE_DIR,
            env={**env, "DJANGO_SETTINGS_MODULE": "config.settings"},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        session_name, csrf_name = result.stdout.strip().splitlines()
        return session_name, csrf_name

    def test_production_config_uses_host_prefixed_cookie_names(self):
        # ASVS V3.3.1: a Secure cookie must carry the __Host- (or
        # __Secure-) prefix, so a browser drops it outright if Secure is
        # ever accidentally lost.
        session_name, csrf_name = self._cookie_names(
            "False", CACHE_URL="rediscache://127.0.0.1:6379/2"
        )

        self.assertEqual(session_name, "__Host-sessionid")
        self.assertEqual(csrf_name, "__Host-csrftoken")

    def test_relaxed_cookies_keep_the_plain_cookie_names(self):
        # The local compose stack runs DEBUG=False but SESSION_COOKIE_SECURE
        # and CSRF_COOKIE_SECURE off (DECISIONS D35), because it serves
        # plain HTTP. A __Host-/__Secure- name there would make the browser
        # refuse the cookie entirely and silently break login.
        session_name, csrf_name = self._cookie_names(
            "False", SESSION_COOKIE_SECURE="False", CSRF_COOKIE_SECURE="False"
        )

        self.assertEqual(session_name, "sessionid")
        self.assertEqual(csrf_name, "csrftoken")


class StaticFilesTests(SimpleTestCase):
    """WhiteNoise, and the middleware order that makes it worth having."""

    def test_whitenoise_sits_directly_after_the_security_header_middleware(self):
        from django.conf import settings

        middleware = settings.MIDDLEWARE
        index = middleware.index("whitenoise.middleware.WhiteNoiseMiddleware")

        # Placed later it would still serve files, having first paid for
        # session lookup, authentication and CSRF on every asset request.
        # SecurityMiddleware and ContentSecurityPolicyMiddleware (security
        # pass 4) only ever set response headers -- neither touches the
        # session, auth or CSRF -- so both can sit ahead of WhiteNoise
        # without a static file paying for any of that.
        self.assertEqual(
            middleware[index - 2 : index],
            [
                "django.middleware.security.SecurityMiddleware",
                "config.middleware.ContentSecurityPolicyMiddleware",
            ],
        )

    def test_static_root_is_configured(self):
        from django.conf import settings

        # Unset, collectstatic refuses to run -- the usual first failure of
        # a container build.
        self.assertTrue(settings.STATIC_ROOT)
