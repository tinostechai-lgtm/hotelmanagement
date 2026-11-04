from django.contrib import admin

from .models import Restaurant


@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "business_type", "city", "phone", "created_at")
    search_fields = ("name", "slug", "phone", "gstin")
