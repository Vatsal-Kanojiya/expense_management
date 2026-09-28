"""Delete security event rows once they are older than the retention period.

Roadmap A3. The trail (accounts.SecurityEvent, written through
accounts/audit.py) is meant to answer "what happened to this account
recently", not to grow forever -- a table nothing ever prunes is exactly
issue 19's shape (`expenses/management/commands/purge_exports.py`) with
login history instead of CSV files. Same pattern: a `--days` override, a
`--dry-run`, and a daily beat entry (CELERY_BEAT_SCHEDULE, config/settings.py).

A plain ``queryset.delete()`` is fine here, unlike ``purge_unverified`` --
these rows own no files and protect nothing, so there is no ordering to
get right.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import SecurityEvent


class Command(BaseCommand):
    help = "Delete security events older than the retention period."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=settings.SECURITY_EVENT_RETENTION_DAYS)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be removed without removing it.",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        stale = SecurityEvent.objects.filter(created_at__lt=cutoff)

        if options["dry_run"]:
            self.stdout.write(
                f"{stale.count()} security event(s) older than {options['days']} days"
            )
            return

        removed = stale.delete()[0]

        self.stdout.write(
            self.style.SUCCESS(
                f"Removed {removed} security event(s) older than {options['days']} days."
            )
        )
