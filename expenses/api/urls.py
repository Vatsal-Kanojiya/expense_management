"""API routes.

A DefaultRouter generates list, detail and the browsable root for each
ViewSet, which is most of the reason to use ViewSets at all.

Versioned in the path. The alternative is a header or a query parameter,
and a path is the one a person can read in a log, paste into a browser and
bookmark. Version one is the only version; the point is that a breaking
change has somewhere to go that is not "break every client".
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CategoryViewSet, ExpenseViewSet, ParticipantViewSet

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("participants", ParticipantViewSet, basename="participant")
router.register("expenses", ExpenseViewSet, basename="expense")

app_name = "api"

urlpatterns = [path("v1/", include((router.urls, "v1")))]
