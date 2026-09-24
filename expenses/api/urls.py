"""API routes.

A DefaultRouter generates list, detail and the browsable root for each
ViewSet, which is most of the reason to use ViewSets at all.

Versioned in the path. The alternative is a header or a query parameter,
and a path is the one a person can read in a log, paste into a browser and
bookmark. Version one is the only version; the point is that a breaking
change has somewhere to go that is not "break every client".
"""

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from accounts.api import urlpatterns as account_urls

from .reports import BalancesView, SettlementViewSet, SettleUpView, SummaryView
from .views import CategoryViewSet, ExpenseViewSet, HealthView, ParticipantViewSet

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("participants", ParticipantViewSet, basename="participant")
router.register("expenses", ExpenseViewSet, basename="expense")
router.register("settlements", SettlementViewSet, basename="settlement")

app_name = "api"

# The schema lives inside the version, not beside it. With namespace
# versioning, drf-spectacular documents the endpoints of the version the
# schema request was made to, so /api/v1/schema/ is exactly the v1 contract
# and a future v2 gets its own. DECISIONS D43.
v1 = [
    *router.urls,
    *account_urls,
    path("summary/", SummaryView.as_view(), name="summary"),
    path("balances/", BalancesView.as_view(), name="balances"),
    path("balances/<int:participant_id>/settle/", SettleUpView.as_view(), name="settle-up"),
    path("health/", HealthView.as_view(), name="health"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api:v1:schema"), name="docs"),
]

urlpatterns = [path("v1/", include((v1, "v1")))]
