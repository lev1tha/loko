from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class LokoUserAdmin(UserAdmin):
    list_display = ("username", "role", "branch", "is_active", "is_staff")
    list_filter = ("role", "branch", "is_active", "is_staff")
    fieldsets = UserAdmin.fieldsets + (("Роль и филиал", {"fields": ("role", "module", "branch")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Роль и филиал", {"fields": ("role", "module", "branch")}),)
