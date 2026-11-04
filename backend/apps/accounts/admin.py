from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Membership, Role, User


@admin.register(User)
class ServoraUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Servora", {"fields": ("phone", "pin")}),)
    list_display = ("username", "first_name", "phone", "is_staff")


admin.site.register(Role)
admin.site.register(Membership)
