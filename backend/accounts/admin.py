from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class LokoUserAdmin(UserAdmin):
    list_display = ("username", "role", "is_active", "is_staff")
    list_filter = ("role", "is_active", "is_staff")
    fieldsets = UserAdmin.fieldsets + (("Роль", {"fields": ("role",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Роль", {"fields": ("role",)}),)
