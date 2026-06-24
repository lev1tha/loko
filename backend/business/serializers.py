from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from finance.models import AppSettings, Currency
from .models import Debt, Deposit


class DepositSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)
    amount_kgs = serializers.SerializerMethodField()

    @extend_schema_field(serializers.DecimalField(max_digits=16, decimal_places=2))
    def get_amount_kgs(self, obj):
        # Депозит в сомах (для итогов): юань × курс, сом как есть.
        if obj.currency == Currency.CNY:
            if not hasattr(self, "_rate"):
                self._rate = AppSettings.load().cny_to_kgs_rate
            return (obj.amount * self._rate).quantize(Decimal("0.01"))
        return obj.amount

    class Meta:
        model = Deposit
        fields = (
            "id",
            "source",
            "account",
            "account_name",
            "amount",
            "amount_kgs",
            "currency",
            "status",
            "status_display",
            "note",
            "date",
            "recognized_date",
            "created_at",
        )
        read_only_fields = ("currency", "status", "recognized_date", "created_at")

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Сумма должна быть больше нуля.")
        return value


class DebtSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Debt
        fields = (
            "id",
            "kind",
            "kind_display",
            "counterparty",
            "amount",
            "currency",
            "status",
            "status_display",
            "note",
            "date",
            "created_at",
        )
        read_only_fields = ("created_at",)
