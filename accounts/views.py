from django.contrib.auth import login
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView

from .forms import SignUpForm


class SignUpView(CreateView):
    """Register a new account and sign the user straight in.

    Signup is the one auth view Django does not ship. It provides the form
    (UserCreationForm) and the login machinery, but not the view that joins
    them, because what should happen after registration — auto-login, email
    confirmation, an approval queue — is a product decision.
    """

    form_class = SignUpForm
    template_name = "registration/signup.html"
    success_url = reverse_lazy("expenses:expense_list")

    def dispatch(self, request, *args, **kwargs):
        # Mirrors LoginView's redirect_authenticated_user. Someone already
        # signed in has no business on the registration page.
        if request.user.is_authenticated:
            return redirect(self.success_url)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)

        # login() rotates the session key, which is what prevents session
        # fixation. Passing the backend explicitly is unnecessary here
        # because only one is configured.
        login(self.request, self.object)

        return response
