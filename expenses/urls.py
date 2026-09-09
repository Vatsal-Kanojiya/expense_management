from django.urls import path

from . import views

# Namespacing lets templates reverse URLs as "expenses:category_list" instead
# of a bare "category_list". Without it, two apps that both define a "list"
# URL name would collide silently.
app_name = "expenses"

urlpatterns = [
    path("categories/", views.CategoryListView.as_view(), name="category_list"),
    path("categories/new/", views.CategoryCreateView.as_view(), name="category_create"),
    path("categories/<int:pk>/edit/", views.CategoryUpdateView.as_view(), name="category_update"),
    path("categories/<int:pk>/delete/", views.CategoryDeleteView.as_view(), name="category_delete"),
]
