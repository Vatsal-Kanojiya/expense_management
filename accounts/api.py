"""The account API: sign up, verify, log in and out, passwords, profile.

Every rule here already exists for the Django pages, and this module reuses
it rather than restating it (DECISIONS D44). ``SignUpForm`` and Django's
password forms validate, ``ratelimit`` throttles, the verification token
generator verifies and ``deletion.delete_account`` deletes. What is new is
only the transport: JSON in, JSON and bearer tokens out (D41).

The views that a signed-out person calls set ``authentication_classes = []``.
Without that, a browser that also holds a Django session cookie would have
the request checked for a CSRF token it has no way to send cross-origin.
"""

import logging

from django.conf import settings
from django.contrib.auth import authenticate as django_authenticate
from django.contrib.auth import get_user_model, logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm, PasswordResetForm, SetPasswordForm
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import update_last_login
from django.contrib.auth.tokens import default_token_generator
from django.urls import path
from django.utils import timezone
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.debug import sensitive_variables
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from expenses.api.common import MessageSerializer, ValidationErrorSerializer, raise_form_errors
from expenses.models import Participant

from . import audit, mfa, ratelimit, totp
from .deletion import delete_account
from .forms import SignUpForm
from .models import RecoveryCode, TOTPDevice
from .models import mfa_enabled as user_has_mfa
from .verification import send_verification_email, verify

User = get_user_model()
logger = logging.getLogger(__name__)

AUTH_TAG = ["Account"]


# --- Shapes ---------------------------------------------------------------


class SelfParticipantSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class MeSerializer(serializers.ModelSerializer):
    """The signed-in user, and the participant that stands for them in splits.

    ``self_participant.id`` is what a client sends as ``paid_by`` for "I
    paid" and lists among ``participants`` for "I was there".
    """

    self_participant = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "date_joined",
            "last_login",
            "self_participant",
        ]
        read_only_fields = ["id", "username", "email", "is_staff", "date_joined", "last_login"]

    @extend_schema_field(SelfParticipantSerializer)
    def get_self_participant(self, user):
        participant = Participant.get_or_create_self(user)
        return {"id": participant.id, "name": participant.name}


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField(help_text="Send as `Authorization: Bearer <access>`.")
    refresh = serializers.CharField(help_text="Exchange at `auth/refresh/` for a new pair.")
    user = MeSerializer()


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(style={"input_type": "password"}, trim_whitespace=False)


class SignupSerializer(serializers.Serializer):
    username = serializers.CharField()
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False)
    password_confirm = serializers.CharField(trim_whitespace=False)


class LinkSerializer(serializers.Serializer):
    """The two halves of a mailed link: ``/verify-email/<uid>/<token>``."""

    uid = serializers.CharField()
    token = serializers.CharField()


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(trim_whitespace=False)
    new_password = serializers.CharField(trim_whitespace=False)
    new_password_confirm = serializers.CharField(trim_whitespace=False)


class PasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(LinkSerializer):
    new_password = serializers.CharField(trim_whitespace=False)
    new_password_confirm = serializers.CharField(trim_whitespace=False)


class DeleteAccountSerializer(serializers.Serializer):
    confirm = serializers.CharField(help_text="The account's username, typed out.")


class MFARequiredSerializer(serializers.Serializer):
    mfa_required = serializers.BooleanField(default=True)
    mfa_ticket = serializers.CharField(help_text="Send back to `auth/mfa/verify/` with a code.")


class MFAVerifySerializer(serializers.Serializer):
    mfa_ticket = serializers.CharField()
    code = serializers.CharField(help_text="A 6-digit authenticator code, or a recovery code.")


class MFAStatusSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    recovery_codes_left = serializers.IntegerField()


class MFASetupSerializer(serializers.Serializer):
    secret = serializers.CharField(help_text="For manual entry, if the QR code can't be scanned.")
    otpauth_uri = serializers.CharField()


class MFAConfirmSerializer(serializers.Serializer):
    code = serializers.CharField()


class MFARecoveryCodesSerializer(serializers.Serializer):
    recovery_codes = serializers.ListField(
        child=serializers.CharField(), help_text="Shown once. Store them somewhere safe."
    )


class MFAConfirmResponseSerializer(TokenPairSerializer, MFARecoveryCodesSerializer):
    pass


class MFADisableSerializer(serializers.Serializer):
    password = serializers.CharField(style={"input_type": "password"}, trim_whitespace=False)
    code = serializers.CharField(help_text="A current authenticator code, or a recovery code.")


class MFARegenerateSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="A current authenticator code.")


PASSWORD_FIELDS = {
    "password1": "password",
    "password2": "password_confirm",
    "new_password1": "new_password",
    "new_password2": "new_password_confirm",
}


def password_errors(password, confirm):
    """Where the password-rule errors should appear.

    Django attaches "too short", "too common" and the like to the
    *confirmation* field. When the two copies match, those errors are about
    the password itself, and a form showing them under "Repeat password"
    would point the user at the wrong box. A real mismatch stays on the
    confirmation.
    """
    if password != confirm:
        return PASSWORD_FIELDS
    return {
        **PASSWORD_FIELDS,
        "password2": "password",
        "new_password2": "new_password",
    }


# --- Helpers --------------------------------------------------------------


def issue_tokens(user):
    """A fresh access/refresh pair, plus the profile a client needs at once."""
    refresh = RefreshToken.for_user(user)
    update_last_login(None, user)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "user": MeSerializer(user).data,
    }


def revoke_refresh_tokens(user, request=None):
    """Blacklist every refresh token the user holds, on every device.

    Access tokens need no list: CHECK_REVOKE_TOKEN ties each one to the
    password hash, so the password change that calls this has already
    ended them.

    Records ``tokens_revoked`` here rather than at each call site (a
    password change or reset, on the web page or the API), so every caller
    gets the event for free and none can forget it.
    """
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)
    audit.record("tokens_revoked", request=request, user=user)


def user_from_uid(uid):
    try:
        return User._default_manager.get(pk=urlsafe_base64_decode(uid).decode())
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return None


def rate_limited(detail):
    return Response(
        {"detail": detail, "code": "rate_limited"}, status=status.HTTP_429_TOO_MANY_REQUESTS
    )


INVALID_LINK = Response(
    {"detail": "This link is invalid or has expired.", "code": "invalid_link"},
    status=status.HTTP_400_BAD_REQUEST,
)

INVALID_TICKET = Response(
    {"detail": "That sign-in has expired. Log in again.", "code": "invalid_ticket"},
    status=status.HTTP_400_BAD_REQUEST,
)

WRONG_CODE = Response({"code": ["That code is wrong."]}, status=status.HTTP_400_BAD_REQUEST)


class PublicView(APIView):
    """For people who are not signed in: no authentication, so no CSRF."""

    authentication_classes = []
    permission_classes = [AllowAny]


# --- Views ----------------------------------------------------------------
#
# @sensitive_variables() below, wherever a method holds a password or a
# raw access/refresh token as a local variable (its own, or -- since the
# decorator marks every frame called from within it -- one of a helper
# it calls, such as issue_tokens()). Django's own auth forms already do
# this for the web pages (django/contrib/auth/forms.py); these DRF views
# have no such form underneath them, so nothing did it for them. Without
# it, an unhandled exception here would show that value in full, in the
# DEBUG=True error page and in the mail_admins traceback email alike
# (config/settings.py's LOGGING) -- SafeExceptionReporterFilter only
# blanks a local variable when a decorator says which ones are sensitive.
# Security pass 5.


class SignupView(PublicView):
    """Register. The account stays inactive until the mailed link is used."""

    @extend_schema(
        tags=AUTH_TAG,
        summary="Sign up",
        request=SignupSerializer,
        responses={
            201: MessageSerializer,
            400: ValidationErrorSerializer,
            429: OpenApiResponse(MessageSerializer, description="Too many sign-ups."),
        },
    )
    @sensitive_variables()
    def post(self, request, *args, **kwargs):
        # The web page's limit, under the same key, so the two share it.
        if ratelimit.is_limited(
            "signup", request, "", ratelimit.SIGNUP_LIMIT, ratelimit.SIGNUP_WINDOW
        ):
            return rate_limited("Too many sign-up attempts. Try again later.")
        ratelimit.record_attempt("signup", request, "", ratelimit.SIGNUP_WINDOW)

        body = SignupSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data

        # Exactly the web's form, so the password validators, the unique
        # email and the lower-casing all apply unchanged.
        form = SignUpForm(
            data={
                "username": data["username"],
                "email": data["email"],
                "password1": data["password"],
                "password2": data["password_confirm"],
            }
        )
        if not form.is_valid():
            raise_form_errors(form, password_errors(data["password"], data["password_confirm"]))

        form.instance.is_active = False
        user = form.save()
        Participant.get_or_create_self(user)
        send_verification_email(user, request, to_frontend=True)
        audit.record("signed_up", request=request, user=user)

        return Response(
            {
                "detail": "Account created. Check your email for a link to activate it.",
                "code": "verification_sent",
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyEmailView(PublicView):
    """Activate an account from the mailed link, and sign it in."""

    @extend_schema(
        tags=AUTH_TAG,
        summary="Verify email",
        request=LinkSerializer,
        responses={200: TokenPairSerializer, 400: MessageSerializer},
    )
    @sensitive_variables()
    def post(self, request, *args, **kwargs):
        body = LinkSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        user = verify(body.validated_data["uid"], body.validated_data["token"], User)
        if user is None:
            return INVALID_LINK

        if not user.is_active:
            user.is_active = True
            user.email_verified_at = timezone.now()
            user.save(update_fields=["is_active", "email_verified_at"])

        audit.record("email_verified", request=request, user=user)

        return Response(issue_tokens(user))


class LoginView(PublicView):
    """Username and password in, a token pair out.

    Throttled with the web login's own limiter and key, so attempts made
    through the page and through the API count against one budget --
    alternating between them buys an attacker nothing.
    """

    @extend_schema(
        tags=AUTH_TAG,
        summary="Log in",
        request=LoginSerializer,
        responses={
            200: OpenApiResponse(
                TokenPairSerializer,
                description="Signed in -- or, for an account with two-step sign-in on, "
                "`{mfa_required: true, mfa_ticket}` instead, with no tokens yet: send the "
                "ticket and a code to `auth/mfa/verify/`.",
            ),
            401: OpenApiResponse(MessageSerializer, description="Wrong username or password."),
            403: OpenApiResponse(
                MessageSerializer, description="Right password, email not yet verified."
            ),
            429: OpenApiResponse(MessageSerializer, description="Too many attempts."),
        },
    )
    @sensitive_variables()
    def post(self, request, *args, **kwargs):
        body = LoginSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        username = body.validated_data["username"]
        password = body.validated_data["password"]

        if ratelimit.login_blocked(request, username):
            audit.record("login_blocked", request=request, username=username)
            return rate_limited("Too many sign-in attempts. Wait a few minutes and try again.")

        # django_authenticate() sends Django's own user_login_failed signal
        # on any rejected attempt, which accounts/signals.py turns into a
        # login_failed event -- no explicit call needed here for that case.
        user = django_authenticate(request, username=username, password=password)

        if user is None:
            ratelimit.record_login_failure(request, username)
            logging.getLogger("django.security").warning(
                "Failed API login for %r from %s", username[:150], ratelimit.client_ip(request)
            )
            # Said apart only when the password was right: someone who knows
            # it learns nothing new, and a real person learns why they are
            # stuck.
            #
            # One password hash on every failed path, whether or not an
            # unverified account exists: hashing only when one does made the
            # response measurably slower for exactly those usernames, which
            # told a stranger which accounts were awaiting verification.
            # Security pass 1.
            pending = User.objects.filter(username=username, is_active=False).first()
            if pending is None:
                make_password(password)
            elif pending.check_password(password):
                return Response(
                    {
                        "detail": "Confirm your email address first: use the link we sent.",
                        "code": "email_not_verified",
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            return Response(
                {"detail": "Wrong username or password.", "code": "invalid_credentials"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        ratelimit.clear_login(request, username)

        if user_has_mfa(user):
            # No tokens, no session -- docs/design/MFA.md. The password was
            # right, so the failed-attempts count clears above as usual,
            # but "signed in" is not recorded until the code is too.
            return Response({"mfa_required": True, "mfa_ticket": mfa.make_ticket(user)})

        # No django.contrib.auth.login() call here -- a JWT pair is handed
        # back instead of a session -- so nothing else records this login.
        audit.record("login_succeeded", request=request, user=user)
        return Response(issue_tokens(user))


class MFAVerifyView(PublicView):
    """The second step: a ticket from `auth/login/` plus a code, tokens out."""

    @extend_schema(
        tags=AUTH_TAG,
        summary="Verify a two-step sign-in code",
        request=MFAVerifySerializer,
        responses={
            200: TokenPairSerializer,
            400: OpenApiResponse(
                ValidationErrorSerializer, description="Wrong code, or an invalid/expired ticket."
            ),
            429: OpenApiResponse(MessageSerializer, description="Too many attempts."),
        },
    )
    @sensitive_variables()
    def post(self, request, *args, **kwargs):
        body = MFAVerifySerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data

        user = mfa.user_for_ticket(data["mfa_ticket"], User)
        if user is None:
            return INVALID_TICKET

        result = mfa.verify_code(user, data["code"], request=request)
        if result is None:
            return rate_limited("Too many attempts. Wait a few minutes and try again.")
        if not result:
            return WRONG_CODE

        audit.record("login_succeeded", request=request, user=user)
        return Response(issue_tokens(user))


class MFAStatusView(APIView):
    """Whether two-step sign-in is on, and how many recovery codes are left."""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=AUTH_TAG, summary="Two-step sign-in status", responses=MFAStatusSerializer)
    def get(self, request, *args, **kwargs):
        enabled = user_has_mfa(request.user)
        left = (
            RecoveryCode.objects.filter(user=request.user, used_at__isnull=True).count()
            if enabled
            else 0
        )
        return Response({"enabled": enabled, "recovery_codes_left": left})


class MFASetupView(APIView):
    """Start (or restart) enrolment: a secret and a QR-code URI, unconfirmed."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=AUTH_TAG,
        summary="Start two-step sign-in setup",
        request=None,
        responses={
            200: MFASetupSerializer,
            400: OpenApiResponse(MessageSerializer, description="Already on."),
        },
    )
    @sensitive_variables()
    def post(self, request, *args, **kwargs):
        if user_has_mfa(request.user):
            return Response(
                {"detail": "Two-step sign-in is already on.", "code": "mfa_already_enabled"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        secret = totp.generate_secret()
        # Replaces any earlier, still-unconfirmed attempt -- the
        # OneToOneField means there is never more than one row.
        TOTPDevice.objects.update_or_create(
            user=request.user,
            defaults={"secret": secret, "confirmed": False, "last_used_step": 0},
        )
        return Response(
            {
                "secret": secret,
                "otpauth_uri": totp.otpauth_uri(secret, request.user.get_username()),
            }
        )


class MFAConfirmView(APIView):
    """Confirm the first code, turning two-step sign-in on."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=AUTH_TAG,
        summary="Confirm two-step sign-in setup",
        request=MFAConfirmSerializer,
        responses={
            200: MFAConfirmResponseSerializer,
            400: OpenApiResponse(
                ValidationErrorSerializer, description="Wrong code, or none pending."
            ),
        },
    )
    @sensitive_variables()
    def post(self, request, *args, **kwargs):
        body = MFAConfirmSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        device = TOTPDevice.objects.filter(user=request.user, confirmed=False).first()
        if device is None:
            return Response(
                {"detail": "Start setup first.", "code": "mfa_setup_not_started"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not device.verify(body.validated_data["code"]):
            return WRONG_CODE

        device.confirmed = True
        device.confirmed_at = timezone.now()
        device.save(update_fields=["confirmed", "confirmed_at"])
        codes = RecoveryCode.generate_set(request.user)

        # A device just took over as the second factor for every future
        # sign-in, so any refresh token issued before it existed should not
        # outlive it -- the same reasoning as a password change.
        revoke_refresh_tokens(request.user, request=request)
        audit.record("mfa_enabled", request=request, user=request.user)

        return Response({**issue_tokens(request.user), "recovery_codes": codes})


class MFADisableView(APIView):
    """Turn two-step sign-in off. Needs the password and a current code."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=AUTH_TAG,
        summary="Turn off two-step sign-in",
        request=MFADisableSerializer,
        responses={
            200: TokenPairSerializer,
            400: OpenApiResponse(ValidationErrorSerializer, description="Wrong password or code."),
            429: OpenApiResponse(MessageSerializer, description="Too many wrong attempts."),
        },
    )
    @sensitive_variables()
    def post(self, request, *args, **kwargs):
        body = MFADisableSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data

        if not user_has_mfa(request.user):
            return Response(
                {"detail": "Two-step sign-in is not on.", "code": "mfa_not_enabled"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        refused = mfa.check_for_change(
            request.user, data["code"], request=request, password=data["password"]
        )
        if refused == "blocked":
            return rate_limited("Too many attempts. Wait a few minutes and try again.")
        if refused == "password":
            return Response({"password": ["Wrong password."]}, status=status.HTTP_400_BAD_REQUEST)
        if refused == "code":
            return WRONG_CODE

        TOTPDevice.objects.filter(user=request.user).delete()
        RecoveryCode.objects.filter(user=request.user).delete()
        revoke_refresh_tokens(request.user, request=request)
        audit.record("mfa_disabled", request=request, user=request.user)

        return Response(issue_tokens(request.user))


class MFARegenerateView(APIView):
    """A fresh set of ten recovery codes, replacing the old set."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=AUTH_TAG,
        summary="Regenerate recovery codes",
        request=MFARegenerateSerializer,
        responses={
            200: MFARecoveryCodesSerializer,
            400: OpenApiResponse(ValidationErrorSerializer, description="Wrong code, or MFA off."),
            429: OpenApiResponse(MessageSerializer, description="Too many wrong attempts."),
        },
    )
    @sensitive_variables()
    def post(self, request, *args, **kwargs):
        body = MFARegenerateSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        device = TOTPDevice.objects.filter(user=request.user, confirmed=True).first()
        if device is None:
            return Response(
                {"detail": "Two-step sign-in is not on.", "code": "mfa_not_enabled"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        refused = mfa.check_for_change(
            request.user, body.validated_data["code"], request=request, recovery_allowed=False
        )
        if refused == "blocked":
            return rate_limited("Too many attempts. Wait a few minutes and try again.")
        if refused == "code":
            return WRONG_CODE

        codes = RecoveryCode.generate_set(request.user)
        audit.record("recovery_codes_regenerated", request=request, user=request.user)
        return Response({"recovery_codes": codes})


class RefreshView(TokenRefreshView):
    """Exchange a refresh token for a new pair. The old refresh token dies."""

    authentication_classes = []

    @extend_schema(tags=AUTH_TAG, summary="Refresh tokens")
    @sensitive_variables()
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class LogoutView(PublicView):
    """Revoke one refresh token: this device is signed out, others are not."""

    @extend_schema(
        tags=AUTH_TAG,
        summary="Log out",
        request=RefreshSerializer,
        responses={204: None, 400: MessageSerializer},
    )
    @sensitive_variables()
    def post(self, request, *args, **kwargs):
        body = RefreshSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        try:
            token = RefreshToken(body.validated_data["refresh"])
            # The claim, not request.user: this endpoint takes no
            # authentication (PublicView), only the refresh token itself,
            # so the token's own subject is the only reliable "who".
            user = User.objects.filter(pk=token.payload.get("user_id")).first()
            token.blacklist()
        except TokenError:
            return Response(
                {"detail": "That token is invalid or already revoked.", "code": "token_invalid"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        audit.record("logged_out", request=request, user=user)

        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordChangeView(APIView):
    """Change the password, sign out every other device, keep this one."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=AUTH_TAG,
        summary="Change password",
        request=PasswordChangeSerializer,
        responses={
            200: TokenPairSerializer,
            400: ValidationErrorSerializer,
            429: OpenApiResponse(MessageSerializer, description="Too many wrong passwords."),
        },
    )
    @sensitive_variables()
    def post(self, request, *args, **kwargs):
        # Wrong current passwords per account, shared with the web page.
        if ratelimit.password_change_blocked(request.user):
            return rate_limited("Too many attempts. Wait a few minutes and try again.")

        body = PasswordChangeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data

        form = PasswordChangeForm(
            request.user,
            data={
                "old_password": data["old_password"],
                "new_password1": data["new_password"],
                "new_password2": data["new_password_confirm"],
            },
        )
        if not form.is_valid():
            if "old_password" in form.errors:
                ratelimit.record_password_change_failure(request.user)
            raise_form_errors(
                form, password_errors(data["new_password"], data["new_password_confirm"])
            )

        ratelimit.clear_password_change(request.user)
        user = form.save()
        revoke_refresh_tokens(user, request=request)
        audit.record("password_changed", request=request, user=user)
        if request.auth is None:
            # Signed in by session: keep that session, as the web page does.
            update_session_auth_hash(request, user)

        # The caller's own tokens died with the old password, so it gets new
        # ones and stays signed in; every other device must log in again.
        return Response(issue_tokens(user))


class PasswordResetView(PublicView):
    """Mail a reset link. The answer is the same whether or not the email exists."""

    @extend_schema(
        tags=AUTH_TAG,
        summary="Request a password reset",
        request=PasswordResetSerializer,
        responses={200: MessageSerializer, 429: MessageSerializer},
    )
    def post(self, request, *args, **kwargs):
        body = PasswordResetSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        email = body.validated_data["email"]

        if ratelimit.is_limited(
            "reset", request, email, ratelimit.RESET_LIMIT, ratelimit.RESET_WINDOW
        ):
            return rate_limited("Too many reset requests. Wait an hour and try again.")
        ratelimit.record_attempt("reset", request, email, ratelimit.RESET_WINDOW)

        # Recorded whether or not the address matches an account -- like
        # the response itself, which never says either way.
        matched_user = User.objects.filter(email__iexact=email).first()
        audit.record("password_reset_requested", request=request, user=matched_user, email=email)

        form = PasswordResetForm(data={"email": email})
        if form.is_valid():
            options = {
                "request": request,
                "use_https": request.is_secure(),
                "subject_template_name": "registration/password_reset_subject.txt",
                "email_template_name": "registration/password_reset_email.html",
            }
            if settings.FRONTEND_URL:
                options["email_template_name"] = "registration/password_reset_email_frontend.txt"
                options["extra_email_context"] = {"frontend_url": settings.FRONTEND_URL}
            form.save(**options)

        return Response(
            {
                "detail": "If an account uses that email, a reset link is on its way.",
                "code": "reset_sent",
            }
        )


class PasswordResetConfirmView(PublicView):
    """Set a new password from a mailed reset link."""

    @extend_schema(
        tags=AUTH_TAG,
        summary="Set a new password from a reset link",
        request=PasswordResetConfirmSerializer,
        responses={200: MessageSerializer, 400: ValidationErrorSerializer},
    )
    @sensitive_variables()
    def post(self, request, *args, **kwargs):
        body = PasswordResetConfirmSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data

        user = user_from_uid(data["uid"])
        if user is None or not default_token_generator.check_token(user, data["token"]):
            return INVALID_LINK

        form = SetPasswordForm(
            user,
            data={
                "new_password1": data["new_password"],
                "new_password2": data["new_password_confirm"],
            },
        )
        if not form.is_valid():
            raise_form_errors(
                form, password_errors(data["new_password"], data["new_password_confirm"])
            )

        form.save()
        revoke_refresh_tokens(user, request=request)
        audit.record("password_reset_completed", request=request, user=user)
        return Response(
            {"detail": "Your password has been set. You can log in now.", "code": "password_set"}
        )


class MeView(APIView):
    """The signed-in account: read it, rename it, or delete it and all its data."""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=AUTH_TAG, summary="Your profile", responses=MeSerializer)
    def get(self, request, *args, **kwargs):
        return Response(MeSerializer(request.user).data)

    @extend_schema(
        tags=AUTH_TAG,
        summary="Update your name",
        request=MeSerializer,
        responses={200: MeSerializer, 400: ValidationErrorSerializer},
    )
    def patch(self, request, *args, **kwargs):
        serializer = MeSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @extend_schema(
        tags=AUTH_TAG,
        summary="Delete your account and everything in it",
        description="Irreversible. Confirm by sending the account's username as `confirm`.",
        request=DeleteAccountSerializer,
        responses={204: None, 400: MessageSerializer},
    )
    def delete(self, request, *args, **kwargs):
        body = DeleteAccountSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        # Typed, not a checkbox -- the same guard as the web page, for the
        # same reason: the usual failure is a mis-click.
        if body.validated_data["confirm"].strip() != request.user.get_username():
            return Response(
                {"detail": "Type your username exactly to confirm.", "code": "confirm_mismatch"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        username = user.get_username()
        if request.auth is None:
            logout(request)
        counts = delete_account(user, request=request)
        logger.info("Account %s deleted through the API: %s", username, counts)
        return Response(status=status.HTTP_204_NO_CONTENT)


urlpatterns = [
    path("auth/signup/", SignupView.as_view(), name="auth-signup"),
    path("auth/verify-email/", VerifyEmailView.as_view(), name="auth-verify-email"),
    path("auth/login/", LoginView.as_view(), name="auth-login"),
    path("auth/mfa/verify/", MFAVerifyView.as_view(), name="auth-mfa-verify"),
    path("auth/mfa/", MFAStatusView.as_view(), name="auth-mfa-status"),
    path("auth/mfa/setup/", MFASetupView.as_view(), name="auth-mfa-setup"),
    path("auth/mfa/confirm/", MFAConfirmView.as_view(), name="auth-mfa-confirm"),
    path("auth/mfa/disable/", MFADisableView.as_view(), name="auth-mfa-disable"),
    path(
        "auth/mfa/recovery-codes/",
        MFARegenerateView.as_view(),
        name="auth-mfa-recovery-codes",
    ),
    path("auth/refresh/", RefreshView.as_view(), name="auth-refresh"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("auth/password/change/", PasswordChangeView.as_view(), name="auth-password-change"),
    path("auth/password/reset/", PasswordResetView.as_view(), name="auth-password-reset"),
    path(
        "auth/password/reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="auth-password-reset-confirm",
    ),
    path("me/", MeView.as_view(), name="me"),
]
