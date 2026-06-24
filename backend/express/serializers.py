from rest_framework import serializers

from .models import Sale


class SaleSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source="account.name", read_only=True)
    is_cash = serializers.BooleanField(read_only=True)
    receivable_som = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    amount_mode_display = serializers.CharField(source="get_amount_mode_display", read_only=True)

    class Meta:
        model = Sale
        fields = (
            "id",
            "client_code",
            "amount_mode",
            "amount_mode_display",
            "weight_kg",
            "places",
            "account",
            "account_name",
            "is_cash",
            # snapshot params (read-only)
            "price_per_kg_usd",
            "usd_rate_som",
            "cost_per_kg_som",
            # amounts
            "price_som",        # начисление (writable in DIRECT mode; recomputed in WEIGHT)
            "paid_som",         # оплата
            "receivable_som",   # дебиторка
            "cost_som",
            "margin_som",
            "date",             # дата операции (ОПиУ)
            "payment_date",     # дата оплаты (ОДДС)
            "created_at",
        )
        read_only_fields = (
            "price_per_kg_usd",
            "usd_rate_som",
            "cost_per_kg_som",
            "cost_som",
            "margin_som",
            "created_at",
        )
        extra_kwargs = {
            "price_som": {"required": False},
            "paid_som": {"required": False},
            "payment_date": {"required": False},
            "weight_kg": {"required": False},
        }

    def validate(self, attrs):
        mode = attrs.get("amount_mode", getattr(self.instance, "amount_mode", Sale.AmountMode.WEIGHT))
        weight = attrs.get("weight_kg", getattr(self.instance, "weight_kg", None))
        price = attrs.get("price_som", getattr(self.instance, "price_som", None))

        if mode == Sale.AmountMode.WEIGHT:
            if not weight or weight <= 0:
                raise serializers.ValidationError({"weight_kg": "Укажите вес больше нуля."})
        else:  # DIRECT
            if price in (None, "") or price <= 0:
                raise serializers.ValidationError({"price_som": "Укажите сумму больше нуля."})
        return attrs
