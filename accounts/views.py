import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import CreateView, TemplateView

from expenses.models import Category, Expense, Participant

from . import audit, mfa, qrcode, ratelimit, totp
from .api import revoke_refresh_tokens
from .deletion import delete_account
from .forms import SignUpForm
from .models import RecoveryCode, TOTPDevice
from .models import mfa_enabled as user_has_mfa
from .verification import send_verification_email, verify

logger = logging.getLogger(__name__)


class ThrottledLoginView(auth_views.LoginView):
    """Login, with attempts counted per (address, username) pair.

    Closes the login half of known issue 15. See accounts/ratelimit.py for
    why the key is that pair and not one or the other.
    """

    redirect_authenticated_user = True

    def form_invalid(self, form):
        username = self.request.POST.get("username", "")
        ratelimit.record_login_failure(self.request, username)
        # Logged to django.security so it lands wherever real security
        # events go, rather than inventing a channel nobody watches.
        logging.getLogger("django.security").warning(
            "Failed login for %r from %s", username[:150], ratelimit.client_ip(self.request)
        )
        return super().form_invalid(form)

    def form_valid(self, form):
        # Clear on success, or ten legitimate logins in a window would lock
        # out exactly the wrong person.
        ratelimit.clear_login(self.request, self.request.POST.get("username", ""))

        user = form.get_user()
        if user_has_mfa(user):
            # No django.contrib.auth.login() here -- the password is right,
            # but the second step is not done yet, so no session for this
            # user may exist (docs/design/MFA.md). cycle_key() rotates the
            # session id the same way login() would, without attaching a
            # user to it, which is what stops a fixation attack on this
            # still-anonymous session.
            self.request.session.cycle_key()
            self.request.session["mfa_ticket"] = mfa.make_ticket(user)
            self.request.session["mfa_next"] = self.get_redirect_url()
            return redirect("accounts:login_mfa")

        return super().form_valid(form)

    def post(self, request, *args, **kwargs):
        username = request.POST.get("username", "")

        if ratelimit.login_blocked(request, username):
            audit.record("login_blocked", request=request, username=username)
            form = self.get_form()
            form.full_clean()
            form.add_error(
                None,
                "Too many sign-in attempts. Wait a few minutes and try again.",
            )
            # 429 rather than 200. A throttled response that looks like a
            # normal failure is invisible to monitoring and to any client
            # that would otherwise back off.
            return self.render_to_response(self.get_context_data(form=form), status=429)

        return super().post(request, *args, **kwargs)


class MFALoginView(View):
    """The code step after a right password, for an account with MFA on.

    Reached only by ``ThrottledLoginView.form_valid`` stashing a ticket in
    the session -- there is no session user yet, so
    ``LoginRequiredMixin`` would be the wrong guard here; the ticket itself
    is what proves the password was already checked.
    """

    template_name = "registration/login_mfa.html"

    def get(self, request, *args, **kwargs):
        if "mfa_ticket" not in request.session:
            return redirect("accounts:login")
        return render(request, self.template_name, {})

    def post(self, request, *args, **kwargs):
        ticket = request.session.get("mfa_ticket")
        if ticket is None:
            return redirect("accounts:login")

        user = mfa.user_for_ticket(ticket, get_user_model())
        if user is None:
            request.session.pop("mfa_ticket", None)
            request.session.pop("mfa_next", None)
            messages.error(request, "That sign-in has expired. Log in again.")
            return redirect("accounts:login")

        code = request.POST.get("code", "")
        result = mfa.verify_code(user, code, request=request)
        if result is None:
            return render(
                request,
                self.template_name,
                {"error": "Too many attempts. Wait a few minutes and try again."},
                status=429,
            )
        if not result:
            return render(request, self.template_name, {"error": "That code is wrong."}, status=400)

        next_url = request.session.pop("mfa_next", "") or ""
        request.session.pop("mfa_ticket", None)

        audit.record("login_succeeded", request=request, user=user)
        # login() rotates the session key again, which is fine -- there is
        # no fixation risk in rotating an already-anonymous session key
        # once more on the way to attaching a user to it.
        login(request, user)

        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect(settings.LOGIN_REDIRECT_URL)


class ThrottledPasswordChangeView(auth_views.PasswordChangeView):
    """Password change, with wrong current passwords counted per account.

    The current password is asked for so that someone holding a signed-in
    session cannot take the account over for good. Unlimited guesses would
    undo that. Security pass 1.
    """

    def post(self, request, *args, **kwargs):
        if ratelimit.password_change_blocked(request.user):
            form = self.get_form()
            form.full_clean()
            form.add_error(None, "Too many attempts. Wait a few minutes and try again.")
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        if "old_password" in form.errors:
            ratelimit.record_password_change_failure(self.request.user)
        return super().form_invalid(form)

    def form_valid(self, form):
        ratelimit.clear_password_change(self.request.user)
        response = super().form_valid(form)
        # update_session_auth_hash (called above, inside super().form_valid)
        # only keeps *this* session signed in; it says nothing about a
        # refresh token some other device is holding. Revoke those too, or
        # a stolen refresh token outlives the password that was supposed to
        # shut it out -- the same gap PasswordChangeView in accounts/api.py
        # already closes for a change made through the API. Security pass 4.
        revoke_refresh_tokens(form.user, request=self.request)
        audit.record("password_changed", request=self.request, user=form.user)
        return response


class ThrottledPasswordResetView(auth_views.PasswordResetView):
    """Password reset, throttled harder than login.

    Closes the reset half of known issue 15. Every accepted request sends
    mail to an address the requester may not own, so the limit is about
    protecting third parties, not just this application.
    """

    def post(self, request, *args, **kwargs):
        email = request.POST.get("email", "")

        if ratelimit.is_limited(
            "reset", request, email, ratelimit.RESET_LIMIT, ratelimit.RESET_WINDOW
        ):
            messages.error(
                request,
                "Too many reset requests. Wait an hour and try again.",
            )
            return redirect("accounts:password_reset_done")

        ratelimit.record_attempt("reset", request, email, ratelimit.RESET_WINDOW)

        # Recorded whether or not the address matches an account -- like
        # the response itself, which never says either way.
        user = get_user_model().objects.filter(email__iexact=email).first()
        audit.record("password_reset_requested", request=request, user=user, email=email)

        return super().post(request, *args, **kwargs)


class ThrottledPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    """Set a new password from a mailed reset link, and end other sign-ins.

    Everything else -- validating the link, the new-password form -- is
    exactly ``PasswordResetConfirmView``; the only addition is closing the
    same gap as ``ThrottledPasswordChangeView.form_valid`` above: a refresh
    token issued before the reset must not outlive it, on the web page and
    not only through the API (``accounts/api.py``'s
    ``PasswordResetConfirmView`` already does this for that path). Not
    itself throttled -- the link is single-use and the mailed request that
    produced it already went through ``ThrottledPasswordResetView``.
    """

    def form_valid(self, form):
        response = super().form_valid(form)
        revoke_refresh_tokens(self.user, request=self.request)
        audit.record("password_reset_completed", request=self.request, user=self.user)
        return response


class SignUpView(CreateView):
    """Register a new account and sign the user straight in.

    Signup is the one auth view Django does not ship. It provides the form
    (UserCreationForm) and the login machinery, but not the view that joins
    them, because what should happen after registration — auto-login, email
    confirmation, an approval queue — is a product decision.
    """

    form_class = SignUpForm
    template_name = "registration/signup.html"
    success_url = reverse_lazy("accounts:verify_email_sent")

    def dispatch(self, request, *args, **kwargs):
        # Mirrors LoginView's redirect_authenticated_user. Someone already
        # signed in has no business on the registration page.
        if request.user.is_authenticated:
            return redirect("expenses:expense_list")
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        # Every attempt counts, not only successful ones: each success mails
        # an address the caller chose, and each failure can say whether a
        # username or email is taken. Security pass 1.
        if ratelimit.is_limited(
            "signup", request, "", ratelimit.SIGNUP_LIMIT, ratelimit.SIGNUP_WINDOW
        ):
            self.object = None
            form = self.get_form()
            form.full_clean()
            form.add_error(None, "Too many sign-up attempts. Try again later.")
            return self.render_to_response(self.get_context_data(form=form), status=429)
        ratelimit.record_attempt("signup", request, "", ratelimit.SIGNUP_WINDOW)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        """Create the account inactive and mail a confirmation link.

        This used to sign the user straight in, which is friendlier and
        meant anyone could register an address they did not control --
        known issue 16. The quiet danger there is not the unwanted account,
        it is that password reset becomes a takeover in reverse: the real
        owner clicks "forgot password" and inherits whatever the impostor
        put in the account.

        is_active is set before the first save, so there is never a moment
        where an unverified account could be signed into.
        """
        form.instance.is_active = False
        response = super().form_valid(form)

        Participant.get_or_create_self(self.object)
        send_verification_email(self.object, self.request)
        audit.record("signed_up", request=self.request, user=self.object)

        return response


class VerifyEmailSentView(TemplateView):
    template_name = "registration/verify_email_sent.html"


class VerifyEmailView(View):
    """Activate an account from a mailed link, and sign it in.

    GET, not POST, because it is reached by clicking a link in an email
    client. That is the one place the usual rule bends: the action is
    idempotent, the token is single-use, and no form could be presented in
    a mail client anyway.
    """

    def get(self, request, uidb64, token, *args, **kwargs):
        user = verify(uidb64, token, get_user_model())

        if user is None:
            messages.error(
                request,
                "That confirmation link is invalid or has expired. Try signing in, "
                "or register again.",
            )
            return redirect("accounts:login")

        if not user.is_active:
            user.is_active = True
            user.email_verified_at = timezone.now()
            user.save(update_fields=["is_active", "email_verified_at"])

        audit.record("email_verified", request=request, user=user)

        # login() rotates the session key, which is what prevents session
        # fixation. Passing the backend explicitly is unnecessary here
        # because only one is configured.
        login(request, user)
        messages.success(request, "Your email is confirmed. Welcome.")

        return redirect("expenses:expense_list")


class DeleteAccountView(LoginRequiredMixin, View):
    """Close an account and destroy everything it owns.

    POST only, and confirmed by typing the username. A password prompt
    would be the other option; a typed name is better here because the
    common failure is a mis-click, not an attacker at an unlocked laptop,
    and re-typing the name forces the person to read what they are about
    to lose.
    """

    template_name = "registration/delete_account.html"

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self._context(request))

    def _context(self, request):
        return {
            "expense_count": Expense.objects.filter(user=request.user).count(),
            "category_count": Category.objects.filter(user=request.user).count(),
        }

    def post(self, request, *args, **kwargs):
        if request.POST.get("confirm", "").strip() != request.user.get_username():
            messages.error(request, "Type your username exactly to confirm.")
            return render(request, self.template_name, self._context(request), status=400)

        user = request.user
        username = user.get_username()

        # Log out before deleting. Afterwards the session points at a row
        # that no longer exists, and the next request would fail loading it.
        logout(request)
        counts = delete_account(user, request=request)

        logger.info("Account %s deleted: %s", username, counts)
        messages.success(request, "Your account and all its data have been deleted.")

        return redirect("accounts:login")


class MFAView(LoginRequiredMixin, View):
    """The account page's "Two-step sign-in" section: status, disable, and
    fresh recovery codes for an account that already has it on.
    """

    template_name = "registration/mfa.html"

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self._context(request))

    def _context(self, request, **extra):
        return {
            "mfa_enabled": user_has_mfa(request.user),
            "recovery_codes_left": RecoveryCode.objects.filter(
                user=request.user, used_at__isnull=True
            ).count(),
            **extra,
        }


class MFASetupView(LoginRequiredMixin, View):
    """Start enrolment and confirm the first code.

    GET starts (or resumes) enrolment: an unconfirmed device always exists
    by the time the page renders, its secret shown as a QR code and as
    text. POSTing a correct code confirms it, generates recovery codes, and
    hands them to :class:`MFARecoveryCodesView` through the session -- the
    one moment they exist outside whatever the user writes down.
    """

    template_name = "registration/mfa_setup.html"

    def get(self, request, *args, **kwargs):
        if user_has_mfa(request.user):
            return redirect("accounts:mfa")

        device, _ = TOTPDevice.objects.get_or_create(
            user=request.user,
            defaults={"secret": totp.generate_secret()},
        )
        return render(request, self.template_name, self._context(device))

    def _context(self, device, **extra):
        uri = totp.otpauth_uri(device.secret, self.request.user.get_username())
        return {
            "secret": device.secret,
            "otpauth_uri": uri,
            "qr_data_uri": qrcode.otpauth_data_uri(uri),
            **extra,
        }

    def post(self, request, *args, **kwargs):
        if user_has_mfa(request.user):
            return redirect("accounts:mfa")

        device = TOTPDevice.objects.filter(user=request.user, confirmed=False).first()
        if device is None:
            messages.error(request, "Start setup again.")
            return redirect("accounts:mfa_setup")

        code = request.POST.get("code", "")
        if not device.verify(code):
            return render(
                request,
                self.template_name,
                self._context(device, error="That code is wrong."),
                status=400,
            )

        device.confirmed = True
        device.confirmed_at = timezone.now()
        device.save(update_fields=["confirmed", "confirmed_at"])
        codes = RecoveryCode.generate_set(request.user)

        # A confirmed device is now this account's second factor, so a
        # refresh token issued before it existed should not outlive it --
        # the session itself is left alone, as for a web password change.
        revoke_refresh_tokens(request.user, request=request)
        audit.record("mfa_enabled", request=request, user=request.user)

        request.session["mfa_recovery_codes"] = codes
        return redirect("accounts:mfa_recovery_codes")


class MFARecoveryCodesView(LoginRequiredMixin, View):
    """The ten fresh recovery codes, shown exactly once, straight from the
    session ``MFASetupView`` or ``MFARegenerateView`` just put them in.
    """

    template_name = "registration/mfa_recovery_codes.html"

    def get(self, request, *args, **kwargs):
        codes = request.session.pop("mfa_recovery_codes", None)
        if not codes:
            return redirect("accounts:mfa")
        return render(request, self.template_name, {"recovery_codes": codes})


class MFADisableView(LoginRequiredMixin, View):
    """Turn two-step sign-in off. Needs the password and a current code."""

    def post(self, request, *args, **kwargs):
        if not user_has_mfa(request.user):
            return redirect("accounts:mfa")

        password = request.POST.get("password", "")
        code = request.POST.get("code", "")

        if not request.user.check_password(password):
            messages.error(request, "Wrong password.")
            return redirect("accounts:mfa")

        device = TOTPDevice.objects.filter(user=request.user, confirmed=True).first()
        code_ok = (device is not None and device.verify(code)) or RecoveryCode.try_use(
            request.user, code
        )
        if not code_ok:
            messages.error(request, "That code is wrong.")
            return redirect("accounts:mfa")

        TOTPDevice.objects.filter(user=request.user).delete()
        RecoveryCode.objects.filter(user=request.user).delete()
        revoke_refresh_tokens(request.user, request=request)
        audit.record("mfa_disabled", request=request, user=request.user)

        messages.success(request, "Two-step sign-in is off.")
        return redirect("accounts:mfa")


class MFARegenerateView(LoginRequiredMixin, View):
    """A fresh set of ten recovery codes. Needs a current authenticator
    code -- not a recovery code, so spending the last one cannot itself be
    used to mint ten more.
    """

    def post(self, request, *args, **kwargs):
        device = TOTPDevice.objects.filter(user=request.user, confirmed=True).first()
        if device is None:
            return redirect("accounts:mfa")

        code = request.POST.get("code", "")
        if not device.verify(code):
            messages.error(request, "That code is wrong.")
            return redirect("accounts:mfa")

        codes = RecoveryCode.generate_set(request.user)
        audit.record("recovery_codes_regenerated", request=request, user=request.user)

        request.session["mfa_recovery_codes"] = codes
        return redirect("accounts:mfa_recovery_codes")
