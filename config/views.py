"""The one custom error view: a 500 page that names a request id.

Security pass 5 (HANDOVER.md). Django's own default ``server_error`` view
(``django.views.defaults.server_error``) renders 500.html with no context
and no context processors at all -- deliberately, so a broken context
processor cannot turn one handled 500 into an unhandled one (see the
template's own comment). 404 already gets the id for free: Django's
default ``page_not_found`` view renders with ``request`` passed in, so the
"request" context processor puts ``request.request_id`` within the
template's reach without any code here.

This view keeps 500's guarantee intact -- ``get_request_id()`` reads a
plain ``ContextVar`` (config/middleware.py), no context processors, no
attribute lookups on ``request`` that could themselves raise -- while
giving the page the one thing worth showing a person who hits a server
error: a short id they can quote, that also labels the matching line in
this process's own logs and any error mail (LOGGING's mail_admins
handler, config/settings.py).
"""

from django.http import HttpResponseServerError
from django.template import loader

from .middleware import get_request_id


def server_error(request, template_name="500.html"):
    template = loader.get_template(template_name)
    return HttpResponseServerError(template.render({"request_id": get_request_id()}))
