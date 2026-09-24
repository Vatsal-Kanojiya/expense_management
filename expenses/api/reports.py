"""Derived numbers: the dashboard, balances, and settling up.

These are not rows a client edits, so they are plain views over the same
functions the Django pages call -- ``summarise``, ``outstanding_balances``,
``settle_up`` -- and never a second implementation of any of them. The
row-locked read-then-write that makes settling safe (phase 13) comes along
for free.
"""

from decimal import Decimal

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from expenses.balances import balances, outstanding_balances
from expenses.cache import cached_summary
from expenses.filters import DateRangeForm
from expenses.models import Participant, Settlement
from expenses.settlements import settle_up
from expenses.summaries import previous_period, summarise

from .common import MessageSerializer, raise_form_errors
from .serializers import MONEY
from .views import IsOwner

REPORTS_TAG = ["Reports"]
BALANCES_TAG = ["Balances"]


def two_places(value):
    return None if value is None else Decimal(value).quantize(Decimal("0.01"))


def date_range_form(request):
    """The pages' own date form. Invalid dates are a 400, not a silent default."""
    form = DateRangeForm(request.query_params)
    if not form.is_valid():
        raise_form_errors(form)
    return form


def range_parameters(default):
    return [
        OpenApiParameter("start", OpenApiTypes.DATE, description=f"From (YYYY-MM-DD). {default}"),
        OpenApiParameter("end", OpenApiTypes.DATE, description=f"To (YYYY-MM-DD). {default}"),
    ]


# --- Shapes ---------------------------------------------------------------


class PersonSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class CategoryTotalSerializer(serializers.Serializer):
    category = serializers.IntegerField()
    category_name = serializers.CharField()
    total = serializers.DecimalField(**MONEY)
    count = serializers.IntegerField()
    share = serializers.DecimalField(**MONEY, help_text="Percentage of the period total.")


class BiggestSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    amount = serializers.DecimalField(**MONEY)
    spent_on = serializers.DateField()
    note = serializers.CharField()
    category_name = serializers.CharField()


class PeriodSerializer(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()
    total = serializers.DecimalField(**MONEY)
    count = serializers.IntegerField()


class SummarySerializer(PeriodSerializer):
    average = serializers.DecimalField(**MONEY)
    biggest = BiggestSerializer(allow_null=True)
    by_category = CategoryTotalSerializer(many=True)
    previous = PeriodSerializer(
        help_text="The previous calendar month for a whole month, else the equally long "
        "window just before."
    )
    change_percent = serializers.DecimalField(
        **MONEY, allow_null=True, help_text="Null when the previous period had no spending."
    )


class BalanceSerializer(serializers.Serializer):
    participant = PersonSerializer()
    amount = serializers.DecimalField(**MONEY)


class BalancesSerializer(serializers.Serializer):
    start = serializers.DateField(allow_null=True)
    end = serializers.DateField(allow_null=True)
    owes_you = BalanceSerializer(many=True, help_text="Still owed to you, after repayments.")
    you_owe = BalanceSerializer(many=True, help_text="Still owed by you, as positive amounts.")
    owes_you_total = serializers.DecimalField(**MONEY)
    you_owe_total = serializers.DecimalField(**MONEY)
    gross = BalanceSerializer(
        many=True, help_text="Before repayments. Positive: they owe you. Negative: you owe them."
    )


class SettlementSerializer(serializers.ModelSerializer):
    participant_name = serializers.CharField(source="participant.name", read_only=True)

    class Meta:
        model = Settlement
        fields = ["id", "participant", "participant_name", "amount", "note", "settled_at"]
        read_only_fields = fields


class SettleRequestSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=255)


class SettleResponseSerializer(MessageSerializer):
    settlement = SettlementSerializer(allow_null=True)


# --- Views ----------------------------------------------------------------


class SummaryView(APIView):
    """The Overview page, as data."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=REPORTS_TAG,
        summary="Spending summary for a period",
        parameters=range_parameters("Defaults to the current month."),
        responses={200: SummarySerializer, 400: OpenApiResponse(description="Invalid dates.")},
    )
    def get(self, request, *args, **kwargs):
        start, end = date_range_form(request).range_or_default()
        user = request.user
        previous_start, previous_end = previous_period(start, end)

        # The dashboard's own cache, version-stamped per user (phase 14).
        current = cached_summary(user, start, end, lambda: summarise(user, start, end))
        previous = cached_summary(
            user,
            previous_start,
            previous_end,
            lambda: summarise(user, previous_start, previous_end),
        )

        biggest = current.biggest
        data = {
            "start": start,
            "end": end,
            "total": current.total,
            "count": current.count,
            "average": two_places(current.average_per_expense),
            "biggest": biggest
            and {
                "id": biggest.id,
                "amount": biggest.amount,
                "spent_on": biggest.spent_on,
                "note": biggest.note,
                "category_name": biggest.category.name,
            },
            "by_category": [
                {
                    "category": row["category_id"],
                    "category_name": row["category__name"],
                    "total": row["total"],
                    "count": row["count"],
                    "share": two_places(row["share"]),
                }
                for row in current.by_category
            ],
            "previous": {
                "start": previous.start,
                "end": previous.end,
                "total": previous.total,
                "count": previous.count,
            },
            "change_percent": two_places(current.change_from(previous)),
        }
        return Response(SummarySerializer(data).data)


class BalancesView(APIView):
    """The Balances page, as data: who owes you, and whom you owe."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=BALANCES_TAG,
        summary="Who owes whom",
        description=(
            "All time unless `start`/`end` narrow it, because settling always settles the "
            "all-time amount (DECISIONS D46). Expenses whose lines do not add up are left out."
        ),
        parameters=range_parameters("Defaults to all time."),
        responses={200: BalancesSerializer, 400: OpenApiResponse(description="Invalid dates.")},
    )
    def get(self, request, *args, **kwargs):
        form = date_range_form(request)
        start, end = form.cleaned_data.get("start"), form.cleaned_data.get("end")

        net = outstanding_balances(request.user, start, end)
        # Split here, not in the client: a minus sign should not need
        # interpreting on every screen that shows a balance.
        owes_you = [(person, amount) for person, amount in net if amount > 0]
        you_owe = [(person, -amount) for person, amount in net if amount < 0]

        def rows(pairs):
            return [
                {"participant": {"id": person.id, "name": person.name}, "amount": amount}
                for person, amount in pairs
            ]

        data = {
            "start": start,
            "end": end,
            "owes_you": rows(owes_you),
            "you_owe": rows(you_owe),
            "owes_you_total": sum((amount for _, amount in owes_you), Decimal("0")),
            "you_owe_total": sum((amount for _, amount in you_owe), Decimal("0")),
            "gross": rows(balances(request.user, start, end)),
        }
        return Response(BalancesSerializer(data).data)


class SettleUpView(APIView):
    """Record that the balance with one person has been paid off, either way."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=BALANCES_TAG,
        summary="Settle up with a person",
        description=(
            "Records a settlement for the whole outstanding amount, in whichever direction it "
            "runs: positive when they paid you back, negative when you paid them. Safe to "
            "retry: a second call finds nothing outstanding."
        ),
        request=SettleRequestSerializer,
        responses={
            201: SettleResponseSerializer,
            200: OpenApiResponse(SettleResponseSerializer, "Nothing was outstanding."),
            404: OpenApiResponse(MessageSerializer, "No such person."),
        },
    )
    def post(self, request, participant_id, *args, **kwargs):
        body = SettleRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        try:
            settlement = settle_up(
                request.user, participant_id, note=body.validated_data.get("note", "")
            )
        except Participant.DoesNotExist:
            # Someone else's person is a 404, like every other detail route.
            return Response(
                {"detail": "No such person.", "code": "not_found"}, status=status.HTTP_404_NOT_FOUND
            )

        if settlement is None:
            return Response(
                {
                    "detail": "Nothing outstanding.",
                    "code": "nothing_outstanding",
                    "settlement": None,
                }
            )

        if settlement.amount > 0:
            detail = f"Recorded {settlement.amount} back from {settlement.participant}."
        else:
            detail = f"Recorded {-settlement.amount} paid to {settlement.participant}."
        return Response(
            {
                "detail": detail,
                "code": "settled",
                "settlement": SettlementSerializer(settlement).data,
            },
            status=status.HTTP_201_CREATED,
        )


class SettlementViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Repayments recorded so far. Read-only: settle up to add one."""

    serializer_class = SettlementSerializer
    permission_classes = [IsAuthenticated, IsOwner]
    queryset = Settlement.objects.select_related("participant")

    def get_queryset(self):
        # Scoped like every other resource: someone else's repayment is a 404.
        return super().get_queryset().filter(user=self.request.user)

    @extend_schema(
        tags=BALANCES_TAG,
        summary="List repayments",
        parameters=[OpenApiParameter("participant", OpenApiTypes.INT, description="A person id.")],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(tags=BALANCES_TAG, summary="Get a repayment")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if participant := self.request.query_params.get("participant"):
            if not participant.isdigit():
                raise serializers.ValidationError({"participant": ["Must be a person id."]})
            queryset = queryset.filter(participant_id=participant)
        return queryset
