"""Background tasks.

The rule every task here follows: **take primary keys, never model
instances.** Arguments are JSON-serialised onto the broker, so an instance
would either fail to serialise or — worse, with pickle — arrive as a stale
snapshot of a row that has since changed. The task re-reads from the
database, which is also what makes a redelivered task see current state.
"""

import csv
import io
import logging

from celery import shared_task
from django.core.files.base import ContentFile
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import ExportJob

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    # Retry on unexpected failures rather than losing the job. Exponential
    # backoff with jitter stops a downstream outage turning every retry into
    # a synchronised thundering herd.
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def build_expense_export(self, job_id: int, site_url: str = "") -> int:
    """Generate the CSV for one ExportJob and email a link to its owner.

    Returns the row count so the result backend carries something useful.

    shared_task rather than @app.task so this module does not import the
    Celery app — it stays importable from anywhere, including tests that
    never start a worker.
    """
    # Re-read rather than trusting anything passed in. With acks_late a
    # redelivered task must see the row as it is now.
    job = ExportJob.objects.select_related("user").get(pk=job_id)

    # Idempotency guard. A redelivery after a successful run must not send a
    # second email or overwrite a file the user may already have downloaded.
    if job.status == ExportJob.Status.COMPLETE:
        logger.info("Export %s already complete; skipping redelivery", job_id)
        return job.row_count

    ExportJob.objects.filter(pk=job_id).update(status=ExportJob.Status.RUNNING)

    try:
        row_count = _write_csv(job)
    except Exception as exc:
        # Record the failure so the user sees something other than a job
        # stuck on "running", then re-raise so Celery's retry logic runs.
        ExportJob.objects.filter(pk=job_id).update(
            status=ExportJob.Status.FAILED, error=str(exc)[:500]
        )
        logger.exception("Export %s failed", job_id)
        raise

    job.refresh_from_db()
    _email_export_ready(job, site_url)
    return row_count


def _write_csv(job: ExportJob) -> int:
    """Stream the user's expenses into the job's FileField."""
    from .models import Expense

    expenses = (
        Expense.objects.for_user(job.user)
        .in_range(job.start, job.end)
        .select_related("category")
        # A plain queryset loads every row into memory at once. iterator()
        # streams in chunks, which is what keeps a ten-year export from
        # exhausting the worker.
        .order_by("spent_on", "id")
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Date", "Category", "Amount", "Note"])

    row_count = 0
    for expense in expenses.iterator(chunk_size=500):
        writer.writerow(
            [
                expense.spent_on.isoformat(),
                expense.category.name,
                f"{expense.amount:.2f}",
                expense.note,
            ]
        )
        row_count += 1

    filename = f"expenses-{job.start:%Y%m%d}-{job.end:%Y%m%d}.csv"
    job.file.save(filename, ContentFile(buffer.getvalue().encode("utf-8")), save=False)

    job.status = ExportJob.Status.COMPLETE
    job.row_count = row_count
    job.completed_at = timezone.now()
    job.save(update_fields=["file", "status", "row_count", "completed_at"])

    return row_count


def _email_export_ready(job: ExportJob, site_url: str) -> None:
    """Email a link, not the file.

    Attachments hit mail-size limits and put a copy of the user's financial
    history in an inbox forever. A link keeps the download behind the
    ownership check in the view.
    """
    path = reverse("expenses:export_download", args=[job.pk])
    body = render_to_string(
        "expenses/email/export_ready.txt",
        {"job": job, "download_url": f"{site_url}{path}"},
    )

    send_mail(
        subject=f"Your expense export is ready ({job.row_count} rows)",
        message=body,
        from_email=None,  # falls back to DEFAULT_FROM_EMAIL
        recipient_list=[job.user.email],
    )


@shared_task
def purge_exports(days=7):
    """Beat's entry point into the retention command.

    A thin wrapper rather than a second implementation, so the scheduled
    path and `manage.py purge_exports` cannot drift apart. The command
    stays runnable by hand, which is what you want at 2am when the
    scheduler is the thing that is broken.
    """
    from django.core.management import call_command

    call_command("purge_exports", days=days)
