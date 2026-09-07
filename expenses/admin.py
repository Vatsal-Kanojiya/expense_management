from django.contrib import admin

# Register your models here.

from .models import Category, Expense


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "created_at")
    list_filter = ("user",)
    search_fields = ("name",)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("spent_on", "amount", "category", "user", "note")
    list_filter = ("category", "spent_on")
    search_fields = ("note",)
    date_hierarchy = "spent_on"
    list_select_related = ("category", "user")