from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Reuse Django's UserAdmin so password hashing, the permissions
    widgets and the add/change fieldset split keep working. Registering
    a plain ModelAdmin here would store passwords in clear text.
    """

    list_display = ("username", "email", "is_staff", "is_active", "date_joined")
    list_filter = ("is_staff", "is_superuser", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("username",)


# --- The admin login, behind the same guard as every other login ---------
#
# admin.site.login is its own view, so the throttling on the web and API
# logins never reached it: the one door that leads to everyone's data had
# no limit at all (security pass 1). Wrapped rather than replaced, so the
# admin keeps its own form, which also refuses non-staff accounts.

_admin_login = admin.site.login


def throttled_admin_login(request, extra_context=None):
    from django.http import HttpResponse

    from . import ratelimit

    if request.method != "POST":
        return _admin_login(request, extra_context)

    username = request.POST.get("username", "")
    if ratelimit.login_blocked(request, username):
        return HttpResponse(
            "Too many sign-in attempts. Wait a few minutes and try again.",
            status=429,
            content_type="text/plain",
        )

    response = _admin_login(request, extra_context)
    # Success redirects; a failed attempt re-renders the form.
    if response.status_code == 302 and request.user.is_authenticated:
        ratelimit.clear_login(request, username)
    else:
        ratelimit.record_login_failure(request, username)
    return response


admin.site.login = throttled_admin_login
