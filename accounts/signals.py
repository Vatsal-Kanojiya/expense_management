"""Connects Django's own login/logout signals to the security event trail.

``user_logged_in`` and ``user_logged_out`` fire from everything that calls
``django.contrib.auth.login()`` / ``logout()`` -- the web pages
(accounts/views.py) and the admin site (accounts/admin.py) alike, since
the admin's own login view ends up calling the same function.
``user_login_failed`` fires from ``authenticate()`` itself, on any backend
rejecting the credentials, so it covers every failed attempt made through
the web pages, the admin, *and* the API's ``LoginView`` (accounts/api.py),
which calls ``authenticate()`` the same way Django's ``AuthenticationForm``
does.

The API's *successful* login never calls ``login()`` -- it hands back a
JWT pair instead of starting a session -- so accounts/api.py records
``login_succeeded`` there explicitly. Nothing here does it a second time
for that path, which is what keeps a login from ever being recorded twice.

The same two signals also keep ``accounts.SignedInDevice`` (docs/design/
SESSION_LIMITS.md) in step: a web sign-in registers the session as a
device, and a web sign-out removes it.
"""

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from . import audit, devices


@receiver(user_logged_in)
def _login_succeeded(sender, request, user, **kwargs):
    audit.record("login_succeeded", request=request, user=user)
    # Every way onto a web session ends in login(): the login page, the MFA
    # code step, Google sign-in, the verify-email link and the admin (which
    # signs in through the site's page). Registering here covers them all
    # (docs/design/SESSION_LIMITS.md).
    if request is not None:
        devices.register_web(request, user)


@receiver(user_login_failed)
def _login_failed(sender, credentials, request=None, **kwargs):
    # authenticate() builds `credentials` from whatever keyword arguments
    # it was called with, sanitising anything that looks like a password
    # (django.contrib.auth.authenticate) -- there is no password in here to
    # accidentally store.
    username = (credentials or {}).get("username", "")
    audit.record("login_failed", request=request, username=username)


@receiver(user_logged_out)
def _logged_out(sender, request, user, **kwargs):
    # user is None when an already-anonymous request hits the logout view;
    # nothing useful to record then.
    if user is not None:
        audit.record("logged_out", request=request, user=user)
    # Fires before logout() flushes the session, so the key is still there.
    # Removed for an anonymous logout too: nothing matches, and nothing breaks.
    session = getattr(request, "session", None)
    if session is not None:
        devices.forget_web(session.session_key)
