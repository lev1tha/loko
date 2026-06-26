from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Debt, Deposit


class DepositSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)
    amount_kgs = serializers.SerializerMethodField()

    @extend_schema_field(serializers.DecimalField(max_digits=16, decimal_places=2))
    def get_amount_kgs(self, obj):
        # Депозит в сомах по СНАПШОТ-курсу (юань × зафиксированный курс).
        return obj.kgs_value

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

    def validate_account(self, value):
        if value is not None and value.module != "BUSINESS":
            raise serializers.ValidationError(
                "Депозит может зачисляться только на счёт направления Business."
            )
        return value

    def validate(self, attrs):
        # После признания/отправки сумму и счёт менять нельзя — иначе молча
        # переписалась бы уже проведённая выручка и её сом-эквивалент.
        inst = self.instance
        if inst is not None and inst.status != Deposit.Status.HELD:
            for f in ("amount", "account", "source", "date"):
                if f in attrs and attrs[f] != getattr(inst, f):
                    raise serializers.ValidationError(
                        {f: "Нельзя менять признанный/отправленный депозит. Создайте корректирующую операцию."}
                    )
        return attrs


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
