"""Backfill email_verified_at for accounts that predate the column.

Roadmap A1. "Unverified" is defined as is_active=False AND
email_verified_at IS NULL, so every account that already exists needs a
value that keeps it out of that definition unless it genuinely never
verified:

* Active accounts were, by construction, verified at some point before
  today -- date_joined is the closest recorded moment (verification and
  sign-up have always happened close together; no better timestamp
  exists). Set from date_joined.
* Inactive accounts with a non-null last_login signed in at least once,
  which only an active account can do -- so they verified, then were
  deactivated by an admin afterwards. Also set from date_joined, for the
  same reason: it is the best timestamp available, and *that* it is set is
  what matters here, not precisely when.
* Inactive accounts that never signed in are left null: nothing tells them
  apart from a genuinely unverified sign-up, and that is exactly the
  purge job's intended target (accounts/management/commands/purge_unverified.py).
"""

from django.db import migrations, models


def backfill(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(is_active=True, email_verified_at__isnull=True).update(
        email_verified_at=models.F("date_joined")
    )
    User.objects.filter(
        is_active=False,
        email_verified_at__isnull=True,
        last_login__isnull=False,
    ).update(email_verified_at=models.F("date_joined"))


def noop(apps, schema_editor):
    # Irreversible in spirit -- there is no way to recover which accounts
    # were "really" unverified before this ran -- but a no-op reverse lets
    # `migrate accounts <earlier>` proceed instead of refusing outright.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_user_email_verified_at"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
