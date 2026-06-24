from rest_framework import serializers

from .models import Debt, Deposit


class DepositSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)

    class Meta:
        model = Deposit
        fields = (
            "id",
            "source",
            "account",
            "account_name",
            "amount",
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
