from django.contrib.auth import views as auth_views
from django.urls import path

app_name = "accounts"

# Routed explicitly rather than via include("django.contrib.auth.urls").
# The include is shorter, but it mounts eight views at once — including
# password reset — and silently 500s on any whose template is missing.
# Listing them makes the surface visible and lets templates land alongside
# the URL that needs them.
urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            # An authenticated user hitting /login/ should go to the app, not
            # be shown a login form again. Safe here only because
            # LOGIN_REDIRECT_URL points elsewhere; pointing it back at login
            # would be an infinite redirect.
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    # LogoutView is POST-only since Django 5.0. A GET logout could be fired
    # by a prefetch, a link scanner or an <img> tag, so the nav uses a form.
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
