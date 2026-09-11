"""Email verification for new accounts.

Known issue 16: anyone could register an account against an address they do
not control. Two things go wrong with that. The obvious one is that the
real owner of the address never consented. The quieter one is that password
reset then becomes an account takeover in reverse -- the real owner clicks
"forgot password", takes the account, and inherits whatever the impostor
put in it.

**No new model and no new column.** Django's ``PasswordResetTokenGenerator``
already produces a signed, expiring, single-use token, and
``is_active=False`` is already the flag that stops a user logging in. A
custom token table would be a second implementation of something the
framework does correctly.

The token is derived from the user's primary key, password hash, and
``last_login``. For verification that gives a useful property for free:
signing in once invalidates every outstanding link, and so does changing
the password.
"""

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """Same machinery, different purpose, deliberately separate instance.

    Subclassed rather than reused so a verification link cannot be replayed
    as a password-reset link. The hash includes ``is_active``, so the token
    stops working the moment the account is verified -- which is what makes
    the link single-use without storing anything.
    """

    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{user.password}{timestamp}{user.is_active}"


token_generator = EmailVerificationTokenGenerator()


def send_verification_email(user, request):
    """Mail a signed activation link.

    The absolute URL is built from the request rather than a setting, so a
    link generated on a staging host points back at staging. In production
    behind a proxy this depends on ALLOWED_HOSTS being right, which it
    already must be.
    """
    path = reverse(
        "accounts:verify_email",
        kwargs={
            "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": token_generator.make_token(user),
        },
    )

    send_mail(
        subject="Confirm your email address",
        message=render_to_string(
            "registration/verify_email.txt",
            {"user": user, "url": request.build_absolute_uri(path)},
        ),
        from_email=None,
        recipient_list=[user.email],
    )


def verify(uidb64, token, user_model):
    """Return the user this link activates, or None.

    None covers every failure -- bad encoding, unknown id, expired token,
    already used -- because distinguishing them for the caller would tell an
    attacker which primary keys exist.
    """
    try:
        pk = urlsafe_base64_decode(uidb64).decode()
        user = user_model._default_manager.get(pk=pk)
    except (TypeError, ValueError, OverflowError, user_model.DoesNotExist):
        return None

    if not token_generator.check_token(user, token):
        return None

    return user
