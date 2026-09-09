"""Email every user a summary of last month's spending.

**Deliberately a management command run by cron, not a Celery task.**

The trigger is a clock, not a request. Nobody is waiting on a response,
so there is nothing to unblock — which is the entire argument for a queue.
Celery Beat would add a broker, a worker and a scheduler process to
babysit for a job that runs twelve times a year. Cron already exists on
every server, and its failure mode (an email from cron) is simpler than a
scheduler silently not firing.

The lesson worth carrying: reach for a queue when the trigger is a
*request*, as the CSV export does. When the trigger is a clock, a command
plus cron is usually the honest answer.

At real scale this changes. Once "every user" is 100,000 rows and SMTP
takes 200ms each, a single sequential run takes hours and one failure
stalls the rest. Then this command becomes a dispatcher — it loops users
and calls a per-user task — and the fan-out argument finally applies. The
idempotency guard below is what makes that migration safe, because it is
already correct for a task that can run twice.

Cron entry (6am on the 1st):

    0 6 1 * * cd /srv/expense-tracker && .venv/bin/python manage.py send_monthly_digests
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string

from expenses.models import MonthlyDigest
from expenses.summaries import month_bounds, previous_period, summarise

User = get_user_model()


class Command(BaseCommand):
    help = "Email each user a summary of the previous calendar month."

    def add_arguments(self, parser):
        parser.add_argument(
            "--month",
            help="Month to send, as YYYY-MM. Defaults to the month before today.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be sent without sending or recording anything.",
        )
        parser.add_argument(
            "--user",
            help="Limit to a single username, for testing.",
        )

    def handle(self, *args, **options):
        month_start = self._resolve_month(options.get("month"))
        month_start, month_end = month_bounds(month_start)
        dry_run = options["dry_run"]

        users = User.objects.filter(is_active=True).exclude(email="")
        if options.get("user"):
            users = users.filter(username=options["user"])

        # Materialise the ids BEFORE looping. queryset.iterator() keeps a
        # server-side cursor open, and the transaction.atomic() commit inside
        # the loop invalidates it — "cursor needed to be reset because of
        # commit/rollback" on the second iteration.
        #
        # This does not show up under TestCase, which wraps each test in a
        # transaction so atomic() is only a savepoint and never really
        # commits. It took running the command for real to surface. See
        # test_digests.DigestCursorTests, which uses TransactionTestCase.
        #
        # Ids only, so the working set stays small; each user is re-fetched
        # in the loop.
        user_ids = list(users.values_list("pk", flat=True))

        sent = skipped = empty = failed = 0

        for user_id in user_ids:
            user = User.objects.get(pk=user_id)
            summary = summarise(user, month_start, month_end)

            # Nothing to report is not worth an email. Recording it anyway
            # would also be wrong: if they later backfill that month, the
            # digest should still be sendable.
            if summary.count == 0:
                empty += 1
                continue

            if dry_run:
                self.stdout.write(
                    f"  would send to {user.email}: {summary.count} expenses, {summary.total}"
                )
                sent += 1
                continue

            # Claim the row BEFORE sending. The unique constraint on
            # (user, month) makes a concurrent or repeated run lose the
            # race and skip, which is what stops a double send when cron
            # fires twice after a restart.
            #
            # This deliberately chooses at-most-once over at-least-once: if
            # the row commits and SMTP then fails, that month is not
            # retried. For a digest, silence beats sending it twice.
            try:
                with transaction.atomic():
                    MonthlyDigest.objects.create(
                        user=user,
                        month=month_start,
                        total=summary.total,
                        expense_count=summary.count,
                    )
            except IntegrityError:
                skipped += 1
                continue

            try:
                self._send(user, summary, month_start, month_end)
            except Exception as exc:  # noqa: BLE001 - one bad address must not stop the run
                failed += 1
                self.stderr.write(self.style.ERROR(f"  {user.email}: {exc}"))
                continue

            sent += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"{month_start:%B %Y}: {sent} sent, {skipped} already sent, "
                f"{empty} with no spending, {failed} failed" + (" (dry run)" if dry_run else "")
            )
        )

    def _resolve_month(self, raw: str | None) -> date:
        if not raw:
            # The month before today. Running on the 1st, that is last month.
            return previous_period(*month_bounds(date.today()))[0]

        try:
            year, month = raw.split("-")
            return date(int(year), int(month), 1)
        except (ValueError, TypeError) as exc:
            raise CommandError(f"--month must look like 2026-09, got {raw!r}") from exc

    def _send(self, user, summary, month_start, month_end):
        previous = summarise(user, *previous_period(month_start, month_end))

        body = render_to_string(
            "expenses/email/monthly_digest.txt",
            {
                "user": user,
                "summary": summary,
                "previous": previous,
                "change": summary.change_from(previous),
            },
        )

        send_mail(
            subject=f"Your {month_start:%B %Y} spending summary",
            message=body,
            from_email=None,
            recipient_list=[user.email],
        )
