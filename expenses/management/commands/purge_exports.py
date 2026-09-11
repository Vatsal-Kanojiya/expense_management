"""Delete generated export files once they are old enough.

Known issue 19: ``media/exports/`` grew without bound, holding complete
copies of users' financial history indefinitely. Every one of those files
is a plaintext CSV of everything the person has ever spent, kept forever
because nobody wrote the job that removes it.

**The row and the file are deleted together, in that order.** Deleting the
row first and failing before the unlink leaves an orphaned file that
nothing references and no future run will find. Deleting the file first and
failing leaves a row pointing at nothing, which the download view already
handles as a 404. The second failure is recoverable and the first is not,
so the file goes first.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from expenses.models import ExportJob

DEFAULT_DAYS = 7


class Command(BaseCommand):
    help = "Delete export files older than the retention period."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be removed without removing it.",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        stale = ExportJob.objects.filter(requested_at__lt=cutoff)

        removed_files = 0

        for job in stale:
            if options["dry_run"]:
                self.stdout.write(f"would remove job {job.pk} ({job.file.name or 'no file'})")
                continue

            if job.file:
                # save=False: the row is about to be deleted anyway, and a
                # save here would write a row we are discarding.
                job.file.delete(save=False)
                removed_files += 1

        if options["dry_run"]:
            self.stdout.write(f"{stale.count()} job(s) older than {options['days']} days")
            return

        removed_rows = stale.delete()[0]

        self.stdout.write(
            self.style.SUCCESS(
                f"Removed {removed_rows} export job(s) and {removed_files} file(s) "
                f"older than {options['days']} days."
            )
        )
