from django.contrib import admin

from .models import Account, AppSettings, Expense, Transfer


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    list_display = ("base_cost_per_kg_som", "price_per_kg_usd", "usd_rate_som", "updated_at")


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("name", "module", "currency", "kind", "initial_balance", "current_balance", "is_active")
    list_filter = ("module", "currency", "kind", "is_active")


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("date", "category", "opex_article", "amount", "account", "description")
    list_filter = ("category", "opex_article", "account", "date")
    search_fields = ("description",)


@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):
    list_display = ("date", "from_account", "to_account", "amount", "to_amount", "rate")
    list_filter = ("from_account", "to_account", "date")
