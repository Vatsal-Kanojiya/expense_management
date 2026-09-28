import secrets

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from . import totp as totp_lib


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
        MFA_CHALLENGE_PASSED = "mfa_challenge_passed", "Two-step code accepted"
        MFA_CHALLENGE_FAILED = "mfa_challenge_failed", "Two-step code rejected"
        MFA_ENABLED = "mfa_enabled", "Two-step sign-in turned on"
        MFA_DISABLED = "mfa_disabled", "Two-step sign-in turned off"
        RECOVERY_CODE_USED = "recovery_code_used", "Recovery code used"
        RECOVERY_CODES_REGENERATED = "recovery_codes_regenerated", "Recovery codes regenerated"

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


class TOTPDevice(models.Model):
    """One authenticator-app secret per user (``docs/design/MFA.md``).

    An unconfirmed row (``confirmed=False``) does nothing -- it exists only
    between "start enrolment" and "confirm the first code" -- and starting
    enrolment again simply replaces it (the ``OneToOneField`` guarantees
    there is never more than one).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="totp_device"
    )
    secret = models.CharField(max_length=32)
    confirmed = models.BooleanField(default=False)
    last_used_step = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"TOTP device for {self.user_id} ({'confirmed' if self.confirmed else 'pending'})"

    def verify(self, code, at=None):
        """Check ``code`` against this device, advancing ``last_used_step``.

        The advance is a conditional ``UPDATE ... WHERE last_used_step <
        step``, not a plain save: two requests racing with the same code
        must not both succeed (no replay, ``docs/design/MFA.md``). Only the
        request whose ``UPDATE`` actually changed a row gets ``True``.
        """
        step = totp_lib.verify(self.secret, code, self.last_used_step, at=at)
        if step is None:
            return False
        changed = TOTPDevice.objects.filter(pk=self.pk, last_used_step__lt=step).update(
            last_used_step=step
        )
        if changed:
            self.last_used_step = step
        return bool(changed)


# Unambiguous: no 0/O, 1/I/L, so a code read off a screen or printout is
# never misread as a different valid-looking character.
RECOVERY_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
RECOVERY_CODE_LENGTH = 10
RECOVERY_CODE_COUNT = 10


def _generate_recovery_code():
    return "".join(secrets.choice(RECOVERY_CODE_ALPHABET) for _ in range(RECOVERY_CODE_LENGTH))


def _normalize_recovery_code(code):
    """Strip whatever separators a person typed and fold to one case."""
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


class RecoveryCode(models.Model):
    """A one-time-use backup code for signing in without the authenticator
    app. Ten per set, shown once; generating a new set replaces the old one.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recovery_codes"
    )
    code_hash = models.CharField(max_length=128)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "used_at"])]

    def __str__(self):
        state = "used" if self.used_at else "unused"
        return f"Recovery code for {self.user_id} ({state})"

    @classmethod
    def generate_set(cls, user):
        """Ten fresh codes for ``user``, replacing any existing set.

        Returns the plaintext codes -- the only moment they exist outside
        someone's own note of them, since only ``code_hash`` is stored.
        """
        codes = [_generate_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
        cls.objects.filter(user=user).delete()
        cls.objects.bulk_create([cls(user=user, code_hash=make_password(code)) for code in codes])
        return codes

    @classmethod
    def try_use(cls, user, code):
        """Spend one of ``user``'s unused codes if ``code`` matches one.

        Checked against every unused hash rather than looked up by value,
        since only the hash is stored. The match is spent with a
        conditional ``UPDATE ... WHERE used_at IS NULL``, the same
        no-double-use guard as ``TOTPDevice.verify``.
        """
        normalized = _normalize_recovery_code(code)
        if not normalized:
            return False
        for candidate in cls.objects.filter(user=user, used_at__isnull=True):
            if check_password(normalized, candidate.code_hash):
                changed = cls.objects.filter(pk=candidate.pk, used_at__isnull=True).update(
                    used_at=timezone.now()
                )
                return bool(changed)
        return False


def mfa_enabled(user):
    """Whether ``user`` has a confirmed authenticator device."""
    return TOTPDevice.objects.filter(user=user, confirmed=True).exists()
