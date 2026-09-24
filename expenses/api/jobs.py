"""Background jobs through the API: CSV exports and bill scans.

Both have the shape the Django pages already use: a request writes one
row, dispatches a Celery task after the commit, and answers at once with
202; the client then polls the row. The tasks are the same tasks. What
this module adds is the transport, and one rule the page enforced by URL
shape alone: a scan becomes an expense at most once.
"""

import mimetypes

from django.conf import settings
from django.db import transaction
from django.http import FileResponse
from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts import ratelimit
from expenses.extraction.prefill import initial_from_scan
from expenses.filters import DateRangeForm
from expenses.forms import BillScanForm
from expenses.models import BillScan, ExportJob
from expenses.tasks import build_expense_export, scan_bill

from .common import MessageSerializer, raise_form_errors
from .serializers import MONEY
from .views import IsOwner

EXPORTS_TAG = ["Exports"]
SCANS_TAG = ["Bill scans"]


class OwnerJobViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, IsOwner]

    def get_queryset(self):
        return super().get_queryset().filter(user=self.request.user)


def not_ready(detail, code="not_ready", **extra):
    return Response({"detail": detail, "code": code, **extra}, status=status.HTTP_409_CONFLICT)


def rate_limited(detail):
    # Same shape as accounts/api.py's own rate_limited: {detail, code}, so a
    # client branches on one field no matter which limit it hit.
    return Response(
        {"detail": detail, "code": "rate_limited"}, status=status.HTTP_429_TOO_MANY_REQUESTS
    )


RATE_LIMIT_RESPONSE = OpenApiResponse(MessageSerializer, description="Too many, too recently.")


# --- Exports --------------------------------------------------------------


class ExportJobSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = ExportJob
        fields = [
            "id",
            "status",
            "start",
            "end",
            "row_count",
            "error",
            "requested_at",
            "completed_at",
            "download_url",
        ]
        read_only_fields = fields

    def get_download_url(self, job) -> str | None:
        if job.status != ExportJob.Status.COMPLETE:
            return None
        return self.context["request"].build_absolute_uri(
            reverse("api:v1:export-download", args=[job.pk])
        )


class ExportRequestSerializer(serializers.Serializer):
    start = serializers.DateField(required=False, help_text="Defaults to the 1st of this month.")
    end = serializers.DateField(required=False, help_text="Defaults to the end of this month.")


@extend_schema_view(
    list=extend_schema(tags=EXPORTS_TAG, summary="List your exports, newest first"),
    retrieve=extend_schema(tags=EXPORTS_TAG, summary="Get an export's status"),
)
class ExportViewSet(OwnerJobViewSet):
    """Request a CSV of your expenses, watch it, download it."""

    serializer_class = ExportJobSerializer
    queryset = ExportJob.objects.all()

    @extend_schema(
        tags=EXPORTS_TAG,
        summary="Request a CSV export",
        description=(
            "Answers at once with the job, status `pending`. A worker builds the file and "
            "emails a link; poll the job until `status` is `complete`, then follow "
            "`download_url`."
        ),
        request=ExportRequestSerializer,
        responses={
            202: ExportJobSerializer,
            400: OpenApiResponse(description="Invalid dates."),
            429: RATE_LIMIT_RESPONSE,
        },
    )
    def create(self, request, *args, **kwargs):
        # Shared with the web page's ExportCreateView, and keyed on the
        # account (accounts/ratelimit.py) -- an export ties up a worker for
        # as long as it takes to build, same reasoning as the scan limit
        # below.
        if ratelimit.export_blocked(request.user):
            return rate_limited("Too many exports requested recently. Try again later.")

        form = DateRangeForm(request.data)
        if not form.is_valid():
            raise_form_errors(form)
        start, end = form.range_or_default()

        job = ExportJob.objects.create(user=request.user, start=start, end=end)
        ratelimit.record_export(request.user)

        site_url = request.build_absolute_uri("/").rstrip("/")
        download_url = f"{settings.FRONTEND_URL}/exports/{job.pk}" if settings.FRONTEND_URL else ""
        # on_commit, as on the page: a worker fast enough to pick the job
        # up before this transaction commits would find no row.
        transaction.on_commit(
            lambda: build_expense_export.delay(job.pk, site_url=site_url, download_url=download_url)
        )

        return Response(self.get_serializer(job).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        tags=EXPORTS_TAG,
        summary="Download a finished export",
        responses={
            (200, "text/csv"): OpenApiTypes.BINARY,
            409: OpenApiResponse(MessageSerializer, "Not finished yet, or it failed."),
        },
    )
    @action(detail=True, methods=["get"])
    def download(self, request, *args, **kwargs):
        job = self.get_object()
        if job.status != ExportJob.Status.COMPLETE or not job.file:
            return not_ready("This export is not ready yet.")

        return FileResponse(
            job.file.open("rb"),
            as_attachment=True,
            filename=f"expenses-{job.start:%Y%m%d}-{job.end:%Y%m%d}.csv",
            content_type="text/csv",
        )


# --- Bill scans -----------------------------------------------------------


class BillScanSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = BillScan
        fields = [
            "id",
            "status",
            "provider",
            "error",
            "result",
            "expense",
            "created_at",
            "completed_at",
            "image_url",
        ]
        read_only_fields = fields

    def get_image_url(self, scan) -> str:
        return self.context["request"].build_absolute_uri(
            reverse("api:v1:bill-scan-image", args=[scan.pk])
        )


class BillScanUploadSerializer(serializers.Serializer):
    image = serializers.FileField(help_text="A JPEG, PNG or WebP photo, at most 5 MB.")


class PrefillItemSerializer(serializers.Serializer):
    name = serializers.CharField()
    amount = serializers.DecimalField(**MONEY)


class ExpensePrefillSerializer(serializers.Serializer):
    """What the model read, shaped as an expense to show, correct and POST."""

    bill_scan = serializers.IntegerField(help_text="Send back unchanged with the expense.")
    category = serializers.IntegerField(
        allow_null=True, help_text="Only when the scan's guess matches one of your categories."
    )
    amount = serializers.DecimalField(**MONEY, allow_null=True)
    spent_on = serializers.DateField()
    note = serializers.CharField(allow_blank=True)
    misc_amount = serializers.DecimalField(**MONEY, allow_null=True)
    misc_note = serializers.CharField(allow_blank=True)
    items = PrefillItemSerializer(many=True)


@extend_schema_view(
    list=extend_schema(tags=SCANS_TAG, summary="List your scanned bills, newest first"),
    retrieve=extend_schema(tags=SCANS_TAG, summary="Get a scan's status and result"),
)
class BillScanViewSet(OwnerJobViewSet):
    """Photograph a bill; a vision model reads it; a person confirms it.

    Nothing here creates an expense. The model's reading only ever becomes
    a draft (``prefill``) that the client shows for correction, and an
    expense exists only when the person saves it with ``POST expenses/``.
    """

    serializer_class = BillScanSerializer
    queryset = BillScan.objects.all()
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(
        tags=SCANS_TAG,
        summary="Upload a bill photo to scan",
        description=(
            "Multipart upload. Answers at once with the scan, status `pending`; poll it "
            "until `done` (then fetch `prefill/`) or `failed` (see `error`)."
        ),
        request={"multipart/form-data": BillScanUploadSerializer},
        responses={
            202: BillScanSerializer,
            400: OpenApiResponse(description="Not a usable photo."),
            429: RATE_LIMIT_RESPONSE,
        },
    )
    def create(self, request, *args, **kwargs):
        # Shared with the web page's BillScanCreateView, and keyed on the
        # account (accounts/ratelimit.py): a scan ties up a worker and, with
        # a real BILL_SCAN_PROVIDER, spends money, so the budget is the
        # account's no matter which client or address it uploads from.
        if ratelimit.scan_blocked(request.user):
            return rate_limited("Too many bills scanned recently. Try again later.")

        # The page's own form: the accepted types and the 5 MB limit.
        form = BillScanForm(request.data, request.FILES)
        if not form.is_valid():
            raise_form_errors(form)

        scan = BillScan.objects.create(user=request.user, image=form.cleaned_data["image"])
        ratelimit.record_scan(request.user)
        transaction.on_commit(lambda: scan_bill.delay(scan.pk))

        return Response(self.get_serializer(scan).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        tags=SCANS_TAG,
        summary="The uploaded photo",
        responses={(200, "image/*"): OpenApiTypes.BINARY},
    )
    @action(detail=True, methods=["get"])
    def image(self, request, *args, **kwargs):
        scan = self.get_object()
        # The extension is trustworthy: BillScanForm.clean_image verified the
        # bytes against their signature at upload and named the file from
        # that, not from whatever the browser claimed. nosniff stops a
        # browser guessing a different type from the bytes themselves, which
        # is exactly the trick that made sniffing at upload necessary.
        content_type, _ = mimetypes.guess_type(scan.image.name)
        response = FileResponse(scan.image.open("rb"), content_type=content_type)
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @extend_schema(
        tags=SCANS_TAG,
        summary="The scan as a draft expense",
        description=(
            "Only for a finished scan that has not been saved yet. Show it for correction, "
            "then `POST expenses/` with the corrected fields and this `bill_scan` id."
        ),
        responses={
            200: ExpensePrefillSerializer,
            409: OpenApiResponse(
                MessageSerializer, "Still scanning (`not_ready`), `failed`, or `already_saved`."
            ),
        },
    )
    @action(detail=True, methods=["get"])
    def prefill(self, request, *args, **kwargs):
        scan = self.get_object()

        if scan.expense_id:
            return not_ready(
                "This bill has already been saved as an expense.",
                code="already_saved",
                expense=scan.expense_id,
            )
        if scan.status == BillScan.Status.FAILED:
            return not_ready("This bill could not be read.", code="failed")
        if scan.status != BillScan.Status.DONE:
            return not_ready("Still scanning. Try again in a moment.")

        initial, lines = initial_from_scan(scan, request.user)
        category = initial.get("category")
        data = {
            "bill_scan": scan.pk,
            "category": category.pk if category else None,
            "amount": initial.get("amount"),
            "spent_on": initial["spent_on"],
            "note": initial.get("note", ""),
            "misc_amount": initial.get("misc_amount"),
            "misc_note": initial.get("misc_note", ""),
            "items": lines,
        }
        return Response(ExpensePrefillSerializer(data).data)
