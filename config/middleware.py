"""Request-scoped context for logs.

Phase 7 added a LOGGING config. It produces correct, complete, and largely
unusable output: under three gunicorn workers the lines from concurrent
requests interleave, and nothing says which line belongs to which request.
A traceback in the middle of that cannot be tied to the request that caused
it.

A request id fixes that, and the mechanism is worth understanding because
it is the one place Django's request/response cycle needs something
genuinely global.
"""

import logging
import uuid
from contextvars import ContextVar

from django.conf import settings
from django.http import HttpResponse

# ContextVar, not threading.local. Under a WSGI worker they behave the
# same; under ASGI a single thread interleaves many requests and a
# thread-local would leak one request's id into another's log lines.
# ContextVar is per-task, which is what "this request" actually means.
_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    return _request_id.get()


class MaxUploadSizeMiddleware:
    """Refuse a request that is already too big, before Django reads it.

    Security pass 2 (HANDOVER.md). Placed first in MIDDLEWARE so nothing
    upstream of it -- not even CsrfViewMiddleware, which reads
    ``request.POST`` to find the token on every unsafe request, forcing a
    full multipart parse -- gets a chance to stream an oversized body into
    memory or a temp file before this rejects it from the header alone.

    A cheap, early check, not a guarantee: Content-Length is whatever the
    client declared, and a request that lies about it or sends the body
    chunked slips past this and lands on DATA_UPLOAD_MAX_MEMORY_SIZE
    (settings.py) instead, later and after more work is done. In
    production the reverse proxy's own body-size limit (HANDOVER.md
    section 4) is the backstop that does not trust the client either way.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        limit = settings.DATA_UPLOAD_MAX_MEMORY_SIZE
        content_length = request.META.get("CONTENT_LENGTH")

        if limit is not None and content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = None

            if declared_size is not None and declared_size > limit:
                return HttpResponse("Request body too large.", status=413)

        return self.get_response(request)


class ContentSecurityPolicyMiddleware:
    """Send a Content-Security-Policy header on every response.

    Security pass 4 (HANDOVER.md). Django has no built-in CSP, so this is
    forty lines rather than a new dependency, in the spirit of
    accounts/ratelimit.py.

    The default policy is close to lock-down: every template's own
    ``<script>`` tag names a static file (grepped before writing this),
    never inline code, so ``script-src`` needs nothing beyond ``'self'``.
    Inline ``style="..."`` attributes and the theme ``<style>`` block in
    base.html and 500.html are everywhere, and rewriting every one into an
    external stylesheet is out of scope for a security pass, so
    ``style-src`` keeps ``'unsafe-inline'`` -- an inline stylesheet cannot
    exfiltrate data or run script, which is why CSP still treats it as far
    lower risk than inline script.

    The one page that needs more is the drf-spectacular Swagger UI at
    ``/api/v1/docs/``: with no sidecar package installed (requirements.txt)
    it loads its JS and CSS from ``SPECTACULAR_SETTINGS``'s default CDN and
    boots itself with an inline ``<script>``, so that one path gets its own
    wider policy instead of loosening the default for every other page.
    The DRF browsable API needs no such allowance -- its JS and CSS ship as
    static files under STATIC_URL, so the default policy already covers it.

    The login and sign-up pages get the same treatment for Google's own
    hosts, when Sign in with Google is on (``GOOGLE_OAUTH_CLIENT_ID``,
    docs/design/GOOGLE_SIGNIN.md): the button is drawn by Google's script,
    in an iframe, with its own network calls and stylesheet. Everywhere
    else keeps the default policy -- the button's own script is a static
    file (accounts/static/accounts/google-signin.js), not inline, so
    ``script-src`` needs only the one extra host, not ``'unsafe-inline'``.
    """

    DEFAULT_POLICY = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "object-src 'none'"
    )

    # Matches SPECTACULAR_SETTINGS['SWAGGER_UI_DIST']'s default host
    # (config/settings.py does not override it, so drf-spectacular's own
    # default applies) -- unpinned on purpose, the same way that setting is.
    SWAGGER_UI_HOST = "https://cdn.jsdelivr.net"
    DOCS_POLICY = (
        "default-src 'self'; "
        f"script-src 'self' 'unsafe-inline' {SWAGGER_UI_HOST}; "
        f"style-src 'self' 'unsafe-inline' {SWAGGER_UI_HOST}; "
        f"img-src 'self' data: {SWAGGER_UI_HOST}; "
        f"font-src 'self' {SWAGGER_UI_HOST}; "
        "connect-src 'self'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "object-src 'none'"
    )

    # Google Identity Services' own hosts, exactly as docs/design/GOOGLE_SIGNIN.md
    # lists them -- one for the loader script, one (with a trailing /gsi/)
    # covering the iframe it draws the button in and the requests it makes.
    GOOGLE_POLICY = (
        "default-src 'self'; "
        "script-src 'self' https://accounts.google.com/gsi/client; "
        "style-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/style; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self' https://accounts.google.com/gsi/; "
        "frame-src https://accounts.google.com/gsi/; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "object-src 'none'"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path == self._docs_path():
            policy = self.DOCS_POLICY
        elif request.path in self._google_signin_paths():
            policy = self.GOOGLE_POLICY
        else:
            policy = self.DEFAULT_POLICY
        response.setdefault("Content-Security-Policy", policy)
        return response

    @staticmethod
    def _docs_path():
        # Resolved through reverse(), not hardcoded, so a future change to
        # expenses/api/urls.py cannot silently leave the Swagger UI page
        # under the strict default policy. Cheap enough to call every
        # request: a handful of string joins, no I/O.
        from django.urls import NoReverseMatch, reverse

        try:
            return reverse("api:v1:docs")
        except NoReverseMatch:
            # Never happens with this project's URLConf; keeps a broken
            # reverse() from turning every response into a 500 rather than
            # just falling back to the strict default policy.
            return None

    @staticmethod
    def _google_signin_paths():
        # Same reasoning as _docs_path() -- resolved, not hardcoded. Applied
        # whether or not Sign in with Google is actually configured: the
        # button is simply absent from the page then (accounts/views.py's
        # GoogleButtonContextMixin), and a wider policy on a page that
        # loads nothing extra grants nothing.
        from django.urls import NoReverseMatch, reverse

        try:
            return {reverse("accounts:login"), reverse("accounts:signup")}
        except NoReverseMatch:
            return set()


class RequestIDMiddleware:
    """Attach an id to every request, and echo it back on the response.

    An inbound X-Request-ID is honoured so a value set by a load balancer
    or an upstream service survives into these logs. That is what makes the
    id useful across service boundaries rather than only inside this one.

    Trusting client input here is deliberate and safe: the value is only
    ever written to a log and a response header, never used to look
    anything up. It is truncated because an unbounded header would
    otherwise let anyone write arbitrarily long lines into the log file.
    """

    HEADER = "HTTP_X_REQUEST_ID"
    RESPONSE_HEADER = "X-Request-ID"
    MAX_LENGTH = 64

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.META.get(self.HEADER, "")
        request_id = incoming[: self.MAX_LENGTH].strip() or uuid.uuid4().hex[:12]

        request.request_id = request_id
        token = _request_id.set(request_id)

        try:
            response = self.get_response(request)
        finally:
            # Reset even when the view raised, or the id outlives the
            # request and labels whatever the worker handles next.
            _request_id.reset(token)

        response[self.RESPONSE_HEADER] = request_id
        return response


class RequestIDFilter(logging.Filter):
    """Put the current request id on every log record.

    A filter rather than a custom formatter or an adapter, because it is
    the only hook that reaches records emitted by Django itself and by
    third-party libraries. Neither of those is going to pass a request id
    to a logging call.
    """

    def filter(self, record):
        record.request_id = get_request_id()
        return True
