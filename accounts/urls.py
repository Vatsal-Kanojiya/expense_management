from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = "accounts"

# Routed explicitly rather than via include("django.contrib.auth.urls").
# The include is shorter, but it mounts eight views at once — including
# password reset — and silently 500s on any whose template is missing.
# Listing them makes the surface visible and lets templates land alongside
# the URL that needs them.
urlpatterns = [
    path(
        "login/",
        # An authenticated user hitting /login/ should go to the app, not
        # be shown a login form again. Safe here only because
        # LOGIN_REDIRECT_URL points elsewhere; pointing it back at login
        # would be an infinite redirect. Set on the view class.
        views.ThrottledLoginView.as_view(),
        name="login",
    ),
    # LogoutView is POST-only since Django 5.0. A GET logout could be fired
    # by a prefetch, a link scanner or an <img> tag, so the nav uses a form.
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("signup/", views.SignUpView.as_view(), name="signup"),
    path("delete/", views.DeleteAccountView.as_view(), name="delete_account"),
    path(
        "signup/check-email/",
        views.VerifyEmailSentView.as_view(),
        name="verify_email_sent",
    ),
    path(
        "verify/<uidb64>/<token>/",
        views.VerifyEmailView.as_view(),
        name="verify_email",
    ),
    # Changing a known password (user is logged in).
    path(
        "password/change/",
        auth_views.PasswordChangeView.as_view(
            success_url=reverse_lazy("accounts:password_change_done")
        ),
        name="password_change",
    ),
    path(
        "password/change/done/",
        auth_views.PasswordChangeDoneView.as_view(),
        name="password_change_done",
    ),
    # Resetting a forgotten password (user is anonymous). Four steps:
    # ask for the email, confirm it was sent, follow the emailed link,
    # confirm the new password was saved.
    path(
        "password/reset/",
        views.ThrottledPasswordResetView.as_view(
            email_template_name="registration/password_reset_email.html",
            subject_template_name="registration/password_reset_subject.txt",
            success_url=reverse_lazy("accounts:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password/reset/sent/",
        auth_views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    # uidb64 identifies the user and token proves the request is recent and
    # unused. The token is derived from the password hash and last_login, so
    # it self-invalidates once the password changes.
    path(
        "password/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            success_url=reverse_lazy("accounts:password_reset_complete")
        ),
        name="password_reset_confirm",
    ),
    path(
        "password/reset/done/",
        auth_views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
]
