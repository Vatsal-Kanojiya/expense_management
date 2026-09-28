"""Delete accounts that never verified their email, once they are old enough.

Roadmap A1, `docs/SECURITY_ROADMAP.md`. Sign-up has always created an
inactive account and mailed a link (accounts/verification.py); nothing
ever removed one that never verifies. Left alone, that account squats the
address -- and now the username too -- forever, so this is exactly
`purge_exports` (expenses/management/commands/purge_exports.py) with a
different table: same shape, same daily beat entry, same reasoning.

**"Unverified" means exactly** ``is_active=False AND email_verified_at IS
NULL``. An account an admin deactivated after it verified keeps
``email_verified_at`` set forever (roadmap A1's data migration backfilled
it for every existing account that qualified), so it is never mistaken
for a squatter here.

Goes through ``accounts.deletion.delete_account`` rather than
``queryset.delete()``, the same way the web and API deletion paths do: an
unverified account can already have a Participant row (created at
sign-up, before verification -- accounts/views.py, accounts/api.py), and a
plain queryset delete would either hit ``ProtectedError`` or leave that
row's files behind. One deletion path, used everywhere an account goes.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.deletion import delete_account
from accounts.models import User


class Command(BaseCommand):
    help = "Delete accounts left unverified past the retention period."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=settings.UNVERIFIED_ACCOUNT_DAYS)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be removed without removing it.",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        stale = User.objects.filter(
            is_active=False,
            email_verified_at__isnull=True,
            date_joined__lt=cutoff,
        )

        if options["dry_run"]:
            for user in stale:
                self.stdout.write(f"would remove user {user.pk} ({user.username!r})")
            self.stdout.write(
                f"{stale.count()} unverified account(s) older than {options['days']} days"
            )
            return

        # list() first: delete_account removes rows out from under this
        # queryset one at a time, and iterating a queryset that is changing
        # underneath it is exactly the kind of bug that only shows up once
        # there is enough data for it to matter.
        removed = 0
        for user in list(stale):
            delete_account(user)
            removed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Removed {removed} unverified account(s) older than {options['days']} days."
            )
        )
