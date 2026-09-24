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
