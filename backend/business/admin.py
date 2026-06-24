from django.contrib import admin

from .models import Debt, Deposit


@admin.register(Deposit)
class DepositAdmin(admin.ModelAdmin):
    list_display = ("date", "source", "amount", "currency", "status", "account")
    list_filter = ("status", "currency", "account")
    search_fields = ("source", "note")


@admin.register(Debt)
class DebtAdmin(admin.ModelAdmin):
    list_display = ("date", "kind", "counterparty", "amount", "currency", "status")
    list_filter = ("kind", "status", "currency")
    search_fields = ("counterparty", "note")
