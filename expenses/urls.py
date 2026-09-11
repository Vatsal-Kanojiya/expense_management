from django.urls import path

from . import views

# Namespacing lets templates reverse URLs as "expenses:category_list" instead
# of a bare "category_list". Without it, two apps that both define a "list"
# URL name would collide silently.
app_name = "expenses"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("expenses/", views.ExpenseListView.as_view(), name="expense_list"),
    path("expenses/new/", views.ExpenseCreateView.as_view(), name="expense_create"),
    path("expenses/<int:pk>/edit/", views.ExpenseUpdateView.as_view(), name="expense_update"),
    path("expenses/<int:pk>/delete/", views.ExpenseDeleteView.as_view(), name="expense_delete"),
    path("exports/", views.ExportListView.as_view(), name="export_list"),
    path("exports/new/", views.ExportCreateView.as_view(), name="export_create"),
    path("exports/<int:pk>/download/", views.ExportDownloadView.as_view(), name="export_download"),
    path("balances/", views.BalanceView.as_view(), name="balances"),
    path(
        "balances/<int:pk>/settle/",
        views.SettleUpView.as_view(),
        name="settle_up",
    ),
    path("people/", views.ParticipantListView.as_view(), name="participant_list"),
    path("people/new/", views.ParticipantCreateView.as_view(), name="participant_create"),
    path(
        "people/<int:pk>/edit/",
        views.ParticipantUpdateView.as_view(),
        name="participant_update",
    ),
    path(
        "people/<int:pk>/delete/",
        views.ParticipantDeleteView.as_view(),
        name="participant_delete",
    ),
    path("categories/", views.CategoryListView.as_view(), name="category_list"),
    path("categories/new/", views.CategoryCreateView.as_view(), name="category_create"),
    path("categories/<int:pk>/edit/", views.CategoryUpdateView.as_view(), name="category_update"),
    path("categories/<int:pk>/delete/", views.CategoryDeleteView.as_view(), name="category_delete"),
]
