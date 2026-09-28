"""Background tasks.

The rule every task here follows: **take primary keys, never model
instances.** Arguments are JSON-serialised onto the broker, so an instance
would either fail to serialise or — worse, with pickle — arrive as a stale
snapshot of a row that has since changed. The task re-reads from the
database, which is also what makes a redelivered task see current state.
"""

import csv
import dataclasses
import io
import logging
import mimetypes

from celery import shared_task
from django.core.files.base import ContentFile
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .extraction import extract_bill
from .extraction.errors import ExtractionError
from .models import BillScan, ExportJob

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
def build_expense_export(self, job_id: int, site_url: str = "", download_url: str = "") -> int:
    """Generate the CSV for one ExportJob and email a link to its owner.

    Returns the row count so the result backend carries something useful.

    shared_task rather than @app.task so this module does not import the
    Celery app — it stays importable from anywhere, including tests that
    never start a worker.

    ``download_url``, when given, is the link the email carries verbatim:
    an export requested through the API links to the separate frontend,
    where the person is signed in, rather than to a Django page where they
    may not be (DECISIONS D45).
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
    _email_export_ready(job, site_url, download_url)
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


def _email_export_ready(job: ExportJob, site_url: str, download_url: str = "") -> None:
    """Email a link, not the file.

    Attachments hit mail-size limits and put a copy of the user's financial
    history in an inbox forever. A link keeps the download behind the
    ownership check in the view.
    """
    if not download_url:
        download_url = site_url + reverse("expenses:export_download", args=[job.pk])
    body = render_to_string(
        "expenses/email/export_ready.txt",
        {"job": job, "download_url": download_url},
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


@shared_task(
    bind=True,
    # Same backoff shape as build_expense_export. A vision API rate-limiting
    # us or timing out is exactly the transient failure this is for.
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def scan_bill(self, scan_id: int) -> None:
    """Read one bill photo and store what a vision model saw.

    Unlike build_expense_export, a failure here does not always mean retry:
    ExtractionError means the model looked and could not read the bill, and
    trying the same image again costs money for no better odds. Any other
    exception is treated as transient, exactly as the export task treats it.
    """
    scan = BillScan.objects.select_related("user").get(pk=scan_id)

    # Idempotency guard, same reasoning as build_expense_export: a
    # redelivery after a successful run must not re-spend on the same image.
    if scan.status == BillScan.Status.DONE:
        logger.info("Bill scan %s already done; skipping redelivery", scan_id)
        return

    BillScan.objects.filter(pk=scan_id).update(status=BillScan.Status.RUNNING)

    with scan.image.open("rb") as f:
        data = f.read()

    # scan.image is being re-opened from storage here, not the upload-time
    # InMemoryUploadedFile -- there is no .content_type to read off it.
    # bill_upload_path (models.py) keeps the original extension for exactly
    # this: guess_type() from the stored filename is reliable, guessing from
    # the storage backend's file object is not.
    mime_type, _ = mimetypes.guess_type(scan.image.name)
    mime_type = mime_type or ""

    try:
        bill = extract_bill(data, mime_type)
    except ExtractionError as exc:
        # The model read the image and could not make sense of it. Not
        # transient -- do not re-raise, or Celery retries a bill that will
        # fail the same way three more times at three more times the cost.
        BillScan.objects.filter(pk=scan_id).update(
            status=BillScan.Status.FAILED, error=str(exc)[:500]
        )
        logger.info("Bill scan %s could not be read: %s", scan_id, exc)
        return
    except Exception as exc:
        # Anything else -- a network error, a bug -- is transient until
        # proven otherwise, so record it and let Celery's retry logic run.
        BillScan.objects.filter(pk=scan_id).update(
            status=BillScan.Status.FAILED, error=str(exc)[:500]
        )
        logger.exception("Bill scan %s failed", scan_id)
        raise

    scan.result = _bill_to_json(bill)
    scan.provider = bill.provider
    scan.status = BillScan.Status.DONE
    scan.completed_at = timezone.now()
    scan.save(update_fields=["result", "provider", "status", "completed_at"])


def _bill_to_json(bill) -> dict:
    """dataclasses.asdict(), with the two types a JSONField cannot hold
    turned into strings first: Decimal (amounts) and date (bill_date).

    Amounts stay strings rather than floats so paise are never rounded by
    the JSON encoder -- the same reason expenses/extraction/normalize.py
    (S4) will parse them back into Decimal on the way out.
    """
    raw = dataclasses.asdict(bill)
    raw["total"] = str(bill.total) if bill.total is not None else None
    raw["tax"] = str(bill.tax)
    raw["bill_date"] = bill.bill_date.isoformat() if bill.bill_date else None
    raw["lines"] = [{"name": line.name, "amount": str(line.amount)} for line in bill.lines]
    return raw
