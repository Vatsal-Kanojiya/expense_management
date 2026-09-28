"""ViewSets, and where an API's security boundary actually lives."""

from decimal import Decimal

from django.db import DatabaseError, connection
from django.db.models import Count, Prefetch, Sum
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from expenses.balances import split_expense
from expenses.filters import ExpenseFilterForm
from expenses.managers import with_category_activity, with_participant_activity
from expenses.models import Category, Expense, ExpenseItem, Participant

from .common import MessageSerializer, raise_form_errors
from .pagination import ExpenseCursorPagination
from .serializers import (
    CategorySerializer,
    ExpenseSerializer,
    ExpenseSplitSerializer,
    ParticipantSerializer,
)


class IsOwner(BasePermission):
    """Object-level ownership.

    Worth being precise about what this does and does not cover:
    ``has_object_permission`` runs only when a view calls
    ``get_object()`` -- detail, update, destroy. **It never runs on list.**
    A ViewSet that relied on this alone would return every user's rows from
    the collection endpoint while correctly refusing them one at a time.

    So this is defence in depth. The boundary is ``get_queryset()``, exactly
    as it is for the server-rendered views, and an unowned id is a 404 there
    rather than a 403 here -- which also avoids confirming the row exists.
    """

    def has_object_permission(self, request, view, obj):
        return obj.user_id == request.user.id


class OwnerScopedViewSet(viewsets.ModelViewSet):
    """Scope every queryset to the requester, and stamp ownership on create.

    The direct analogue of OwnerScopedMixin and OwnerFormMixin. `user` is
    never a writable field, so ownership cannot be reassigned by a payload.
    """

    permission_classes = [IsAuthenticated, IsOwner]

    def get_queryset(self):
        return super().get_queryset().filter(user=self.request.user)

    def perform_create(self, serializer):
        # No cache invalidation here any more. A post_save receiver in
        # expenses/signals.py covers every write path at once, including
        # the admin and the shell, which this never could.
        serializer.save(user=self.request.user)


class AnnotatedWritesMixin:
    """Answer a create or update with the same annotated row a GET returns.

    The counts and totals come from annotations on get_queryset(), which a
    freshly saved instance does not carry. Re-reading it through the queryset
    means a client never sees a field that is there on GET and missing on
    POST.
    """

    def perform_create(self, serializer):
        super().perform_create(serializer)
        serializer.instance = self.get_queryset().get(pk=serializer.instance.pk)

    def perform_update(self, serializer):
        super().perform_update(serializer)
        serializer.instance = self.get_queryset().get(pk=serializer.instance.pk)


@extend_schema_view(
    list=extend_schema(summary="List categories, with usage"),
    create=extend_schema(summary="Create a category"),
    retrieve=extend_schema(summary="Get a category"),
    update=extend_schema(summary="Rename a category"),
    partial_update=extend_schema(summary="Rename a category"),
    destroy=extend_schema(
        summary="Delete a category",
        responses={204: None, 409: OpenApiResponse(MessageSerializer, "It still has expenses.")},
    ),
)
class CategoryViewSet(AnnotatedWritesMixin, OwnerScopedViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

    def get_queryset(self):
        return with_category_activity(super().get_queryset())


SELF_REFUSAL = {
    "detail": "This is you. It can't be renamed or deleted; it stands for you in every split.",
    "code": "self_participant",
}


@extend_schema_view(
    list=extend_schema(summary="List people, including yourself (is_self)"),
    create=extend_schema(summary="Add a person"),
    retrieve=extend_schema(summary="Get a person"),
    update=extend_schema(
        summary="Rename a person",
        responses={200: ParticipantSerializer, 403: MessageSerializer},
    ),
    partial_update=extend_schema(
        summary="Rename a person",
        responses={200: ParticipantSerializer, 403: MessageSerializer},
    ),
    destroy=extend_schema(
        summary="Remove a person",
        responses={
            204: None,
            403: OpenApiResponse(MessageSerializer, "That is you."),
            409: OpenApiResponse(MessageSerializer, "They are on a line item or paid a bill."),
        },
    ),
)
class ParticipantViewSet(AnnotatedWritesMixin, OwnerScopedViewSet):
    queryset = Participant.objects.all()
    serializer_class = ParticipantSerializer

    def get_queryset(self):
        return with_participant_activity(super().get_queryset())

    # The self participant is listed, because a client needs its id, but it
    # cannot be renamed -- the owner would then appear under a friend's name
    # -- or deleted, which would strand `paid_by` on every expense the owner
    # paid (issue 34). The People page never offered either.
    def update(self, request, *args, **kwargs):
        if self.get_object().is_self:
            return Response(SELF_REFUSAL, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if self.get_object().is_self:
            return Response(SELF_REFUSAL, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


EXPENSE_FILTERS = [
    OpenApiParameter("start", OpenApiTypes.DATE, description="On or after (YYYY-MM-DD)."),
    OpenApiParameter("end", OpenApiTypes.DATE, description="On or before (YYYY-MM-DD)."),
    OpenApiParameter("category", OpenApiTypes.INT, description="A category id."),
    OpenApiParameter(
        "search", OpenApiTypes.STR, description="Matches the note, line items and people."
    ),
    OpenApiParameter("page_size", OpenApiTypes.INT, description="1-100, default 25."),
]


@extend_schema_view(
    list=extend_schema(
        summary="List expenses, newest date first",
        description=(
            "All time unless `start`/`end` narrow it. `count` and `total_amount` cover the "
            "whole filtered set, not just this page. Follow `next` for more."
        ),
        parameters=EXPENSE_FILTERS,
        responses=inline_serializer(
            "ExpensePage",
            {
                "next": serializers.URLField(allow_null=True),
                "previous": serializers.URLField(allow_null=True),
                "count": serializers.IntegerField(),
                "total_amount": serializers.DecimalField(max_digits=12, decimal_places=2),
                "results": ExpenseSerializer(many=True),
            },
        ),
    ),
    create=extend_schema(summary="Create an expense"),
    retrieve=extend_schema(summary="Get an expense"),
    update=extend_schema(summary="Replace an expense"),
    partial_update=extend_schema(summary="Change part of an expense"),
    destroy=extend_schema(summary="Delete an expense"),
)
class ExpenseViewSet(OwnerScopedViewSet):
    serializer_class = ExpenseSerializer
    pagination_class = ExpenseCursorPagination

    # Nested serializers are an N+1 waiting to happen: each expense
    # serialises its items, each item its shares, each share its
    # participant. The prefetch is not an optimisation here, it is the
    # difference between one page of results and a few hundred queries.
    queryset = Expense.objects.select_related("category", "paid_by").prefetch_related(
        "participants",
        Prefetch("items", queryset=ExpenseItem.objects.prefetch_related("shares")),
    )

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "split":
            # The split names every sharer, so it needs them loaded too.
            # prefetch_related(None) first: a second, different Prefetch of
            # "items" is a ValueError, and get_object() turns a ValueError
            # into a bare 404 -- which is how this first failed.
            queryset = queryset.prefetch_related(None).prefetch_related(
                "participants",
                Prefetch(
                    "items", queryset=ExpenseItem.objects.prefetch_related("shares__participant")
                ),
            )
        return queryset

    def filter_queryset(self, queryset):
        """The Expenses page's filters, validated by the page's own form.

        Only for the list: a filter must never make a single expense 404.
        An invalid value (`start=banana`, another user's category) is a
        400 naming the parameter, where the page would quietly ignore it.
        """
        queryset = super().filter_queryset(queryset)
        if self.action != "list":
            return queryset

        form = ExpenseFilterForm(self.request.query_params, user=self.request.user)
        if not form.is_valid():
            raise_form_errors(form)
        return form.apply(queryset, default_to_month=False)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        response = self.get_paginated_response(self.get_serializer(page, many=True).data)

        # One aggregate over the whole filtered set: the Expenses page shows
        # the filtered total, and a client cannot add up pages it has not
        # fetched. Over the distinct primary keys, because a search joins to
        # items and people and would otherwise count an expense once per
        # match -- the same reason ExpenseQuerySet.total() does it this way.
        totals = Expense.objects.filter(pk__in=queryset.order_by().values("pk")).aggregate(
            count=Count("pk"), total=Sum("amount")
        )
        response.data["count"] = totals["count"]
        response.data["total_amount"] = f"{totals['total'] or Decimal('0'):.2f}"
        return response

    @extend_schema(
        summary="Who owes what on this expense",
        description=(
            "The Split tab. Each row is one person's share of the line items (or of the even "
            "split) and of the misc amount. When the lines do not add up, `is_balanced` is "
            "false and `rows` is empty: the expense is left out of balances until fixed."
        ),
        responses=ExpenseSplitSerializer,
    )
    @action(detail=True, methods=["get"])
    def split(self, request, *args, **kwargs):
        expense = self.get_object()
        rows = split_expense(expense) or []
        me = Participant.get_or_create_self(request.user)

        def person(participant):
            participant = participant or me  # None is the owner
            return {"id": participant.id, "name": participant.name, "is_self": participant.is_self}

        data = {
            "expense": expense.id,
            "is_balanced": expense.is_balanced(),
            "unaccounted_amount": (
                None if expense.items_total() is None else expense.unaccounted_amount()
            ),
            "rows": [
                {
                    "participant": person(r.participant),
                    "items": r.items,
                    "misc": r.misc,
                    "total": r.total,
                }
                for r in rows
            ],
            "items_total": sum((r.items for r in rows), Decimal("0")),
            "misc_total": sum((r.misc for r in rows), Decimal("0")),
            "grand_total": sum((r.total for r in rows), Decimal("0")),
        }
        return Response(ExpenseSplitSerializer(data).data)


class HealthView(APIView):
    """Whether the app is up and can reach its database.

    For a load balancer, an uptime monitor, or a frontend deciding whether
    to show "we are down". Unauthenticated and unthrottled: a monitor
    polling once a minute would otherwise use up the anonymous rate on its
    own.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(
        summary="Health check",
        responses={
            200: inline_serializer("Health", {"status": serializers.CharField()}),
            503: inline_serializer("HealthDown", {"status": serializers.CharField()}),
        },
    )
    def get(self, request, *args, **kwargs):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except DatabaseError:
            return Response({"status": "unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"status": "ok"})
