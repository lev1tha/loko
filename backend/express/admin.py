from django.contrib import admin

from .models import Sale


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "client_code",
        "amount_mode",
        "weight_kg",
        "account",
        "price_som",
        "paid_som",
        "cost_som",
        "margin_som",
    )
    list_filter = ("amount_mode", "account", "date")
    search_fields = ("client_code",)
    readonly_fields = ("cost_som", "margin_som")
