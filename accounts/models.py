from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Project user.

    Extends AbstractUser rather than AbstractBaseUser: the username,
    password, permissions and staff flags are all wanted as-is, so there is
    no reason to rebuild them.

    The only override is email. AbstractUser declares it blank and
    non-unique, which breaks password reset — the reset form looks users up
    by email, so a blank or duplicated address means either no match or an
    ambiguous one. Making it required and unique is what turns
    "reset my password" into a reliable flow rather than a best-effort one.
    """

    email = models.EmailField(
        "email address",
        unique=True,
        help_text="Used to sign in to support and to reset your password.",
    )

    # AbstractUser already sets REQUIRED_FIELDS = ["email"], so createsuperuser
    # prompts for it. Restated here only because the guarantee now matters.
    REQUIRED_FIELDS = ["email"]

    # Set the moment verification succeeds (accounts/verification.py's
    # web and API callers), and left null for everyone else -- including an
    # account createsuperuser or the admin made active directly, which
    # never went through a link to verify. "Unverified" (roadmap A1) means
    # exactly is_active=False AND email_verified_at IS NULL: an admin who
    # deactivates a verified account must never make it look unverified
    # again, or the purge job below would delete a real account. See
    # accounts/management/commands/purge_unverified.py.
    email_verified_at = models.DateTimeField(null=True, blank=True)


class SecurityEvent(models.Model):
    """One row per security-relevant thing that happened: sign-ins and
    failures, password changes and resets, verification, token
    revocation, account deletion. Roadmap A3 -- until now only a failed
    login was logged at all (accounts/views.py, django.security), and
    only to a log file nothing queries.

    Written through accounts.audit.record, never directly: that function
    is what guarantees a failure here never breaks the request it is
    riding along with, and that nothing secret ends up in ``detail``.

    ``user`` is SET_NULL rather than CASCADE -- a deleted account's earlier
    events are kept for the trail (with ``username`` blanked, see
    accounts.deletion.delete_account), not erased with it.
    """

    class Event(models.TextChoices):
        LOGIN_SUCCEEDED = "login_succeeded", "Login succeeded"
        LOGIN_FAILED = "login_failed", "Login failed"
        LOGIN_BLOCKED = "login_blocked", "Login blocked (rate limited)"
        LOGGED_OUT = "logged_out", "Logged out"
        SIGNED_UP = "signed_up", "Signed up"
        EMAIL_VERIFIED = "email_verified", "Email verified"
        PASSWORD_CHANGED = "password_changed", "Password changed"
        PASSWORD_RESET_REQUESTED = "password_reset_requested", "Password reset requested"
        PASSWORD_RESET_COMPLETED = "password_reset_completed", "Password reset completed"
        TOKENS_REVOKED = "tokens_revoked", "Tokens revoked"
        ACCOUNT_DELETED = "account_deleted", "Account deleted"

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    event = models.CharField(max_length=32, choices=Event.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="security_events",
    )
    # A snapshot, not a live lookup -- a failed login can name an account
    # that does not exist, and a deleted account's rows keep no name at all.
    username = models.CharField(max_length=150, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    # Small, structured context (e.g. {"email": "..."} for a reset request).
    # Never a password, token, code or hash -- see accounts/audit.py.
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["event", "created_at"])]

    def __str__(self):
        who = self.username or (self.user_id and f"user {self.user_id}") or "unknown"
        return f"{self.get_event_display()} — {who} @ {self.created_at:%Y-%m-%d %H:%M}"
