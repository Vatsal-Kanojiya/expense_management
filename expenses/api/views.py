"""ViewSets, and where an API's security boundary actually lives."""

from django.db import DatabaseError, connection
from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from expenses.models import Category, Expense, ExpenseItem, Participant

from .serializers import CategorySerializer, ExpenseSerializer, ParticipantSerializer


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


class CategoryViewSet(OwnerScopedViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class ParticipantViewSet(OwnerScopedViewSet):
    queryset = Participant.objects.all()
    serializer_class = ParticipantSerializer


class ExpenseViewSet(OwnerScopedViewSet):
    serializer_class = ExpenseSerializer
    filterset_fields = ["category"]

    # Nested serializers are an N+1 waiting to happen: each expense
    # serialises its items, each item its shares, each share its
    # participant. The prefetch is not an optimisation here, it is the
    # difference between one page of results and a few hundred queries.
    queryset = Expense.objects.select_related("category").prefetch_related(
        "participants",
        Prefetch("items", queryset=ExpenseItem.objects.prefetch_related("shares")),
    )

    def get_queryset(self):
        queryset = super().get_queryset()

        if category := self.request.query_params.get("category"):
            queryset = queryset.filter(category_id=category)

        return queryset


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
