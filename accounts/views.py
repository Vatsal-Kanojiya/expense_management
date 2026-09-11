import logging

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, TemplateView

from expenses.models import Category, Expense

from . import ratelimit
from .deletion import delete_account
from .forms import SignUpForm
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
        ratelimit.record_attempt("login", self.request, username, ratelimit.LOGIN_WINDOW)
        # Logged to django.security so it lands wherever real security
        # events go, rather than inventing a channel nobody watches.
        logging.getLogger("django.security").warning(
            "Failed login for %r from %s", username[:150], ratelimit.client_ip(self.request)
        )
        return super().form_invalid(form)

    def form_valid(self, form):
        # Clear on success, or ten legitimate logins in a window would lock
        # out exactly the wrong person.
        ratelimit.clear("login", self.request, self.request.POST.get("username", ""))
        return super().form_valid(form)

    def post(self, request, *args, **kwargs):
        username = request.POST.get("username", "")

        if ratelimit.is_limited(
            "login", request, username, ratelimit.LOGIN_LIMIT, ratelimit.LOGIN_WINDOW
        ):
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

        return super().post(request, *args, **kwargs)


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

        send_verification_email(self.object, self.request)

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
            user.save(update_fields=["is_active"])

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
        counts = delete_account(user)

        logger.info("Account %s deleted: %s", username, counts)
        messages.success(request, "Your account and all its data have been deleted.")

        return redirect("accounts:login")
