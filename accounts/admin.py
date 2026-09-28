from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import SecurityEvent, User


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


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    """Read-only: this is an audit trail, and an audit trail nobody can
    edit or delete from the admin is the only kind worth keeping. Rows
    are written exclusively through accounts.audit.record and pruned only
    by the retention job (accounts/management/commands/purge_security_events.py).
    """

    list_display = ("created_at", "event", "username", "user", "ip")
    list_filter = ("event", "created_at")
    search_fields = ("username", "ip")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# --- The admin login redirects to the site login -------------------------
#
# The admin's own login form has no second step, so a staff account with
# two-step sign-in on could use it to skip the code entirely (security pass
# 1 threw a throttle around the admin's own form instead; docs/design/MFA.md
# replaces that with this redirect). Signing in at /accounts/login/ instead
# gives the same session the site would have created -- MFA included, and
# throttled exactly as any other sign-in is -- and the admin, which only
# checks that session for is_staff, accepts it the same way it always did.
# There is no throttling logic here any more: the site login's is the only
# one in play.


def admin_login_redirects_to_site_login(request, extra_context=None):
    from django.shortcuts import redirect
    from django.urls import reverse

    return redirect(f"{reverse('accounts:login')}?next={reverse('admin:index')}")


admin.site.login = admin_login_redirects_to_site_login
