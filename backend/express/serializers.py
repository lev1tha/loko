from rest_framework import serializers

from .models import ClientPrice, Sale


class SaleSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source="account.name", read_only=True)
    is_cash = serializers.BooleanField(read_only=True)
    receivable_som = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    # Расчётный («предположительный») вес — для показа админу, в т.ч. в «прямой сумме».
    est_weight_kg = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True, allow_null=True
    )
    amount_mode_display = serializers.CharField(source="get_amount_mode_display", read_only=True)

    class Meta:
        model = Sale
        fields = (
            "id",
            "client_code",
            "amount_mode",
            "amount_mode_display",
            "weight_kg",
            "est_weight_kg",
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
            "cost_som",          # себестоимость (writable при cost_is_manual=true)
            "cost_is_manual",
            "margin_som",
            "date",             # дата операции (ОПиУ)
            "payment_date",     # дата оплаты (ОДДС)
            "created_at",
        )
        read_only_fields = (
            "price_per_kg_usd",
            "usd_rate_som",
            "cost_per_kg_som",
            "margin_som",
            "est_weight_kg",
            "created_at",
        )
        extra_kwargs = {
            "price_som": {"required": False},
            "paid_som": {"required": False},
            "payment_date": {"required": False},
            "weight_kg": {"required": False},
            "cost_som": {"required": False},
            "cost_is_manual": {"required": False},
        }

    def validate_weight_kg(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Вес не может быть отрицательным.")
        return value

    def validate(self, attrs):
        mode = attrs.get("amount_mode", getattr(self.instance, "amount_mode", Sale.AmountMode.WEIGHT))
        price = attrs.get("price_som", getattr(self.instance, "price_som", None))
        # Вес необязателен (Express/общий). В режиме «прямая сумма» нужна сумма.
        if mode == Sale.AmountMode.DIRECT and (price in (None, "") or price <= 0):
            raise serializers.ValidationError({"price_som": "Укажите сумму больше нуля."})

        # Продажа Express относится только к счёту Express в сомах — иначе сумма
        # начисления (всегда в сомах) и остаток счёта (×курс) разойдутся.
        account = attrs.get("account", getattr(self.instance, "account", None))
        if account is not None:
            if account.module != "EXPRESS":
                raise serializers.ValidationError(
                    {"account": "Продажа Express может зачисляться только на счёт направления Express."}
                )
            if account.currency != "KGS":
                raise serializers.ValidationError(
                    {"account": "Счёт продажи Express должен быть в сомах (KGS)."}
                )

        # Оплата в пределах начисления: 0 ≤ оплачено ≤ начислено (нет «переплаты»/минуса).
        paid = attrs.get("paid_som", None)
        if paid is None and self.instance is not None:
            paid = self.instance.paid_som
        if paid is not None:
            if paid < 0:
                raise serializers.ValidationError({"paid_som": "Оплата не может быть отрицательной."})
            ref_price = price if price not in (None, "") else getattr(self.instance, "price_som", None)
            if ref_price is not None and paid > ref_price:
                raise serializers.ValidationError(
                    {"paid_som": "Оплата не может превышать сумму начисления."}
                )

        # Ручная себестоимость требует значения — иначе она тихо считается 0
        # и маржа завышается (см. _apply_pricing).
        if attrs.get("cost_is_manual") and attrs.get("cost_som") in (None, "") and self.instance is None:
            raise serializers.ValidationError(
                {"cost_som": "Укажите себестоимость при ручном вводе."}
            )
        return attrs


class OperatorSaleSerializer(SaleSerializer):
    """Сериализатор для роли «Сотрудник».

    Без финансовых полей (себестоимость, маржа, ставки, дебиторка) — ни в ответе,
    ни на запись. Оператор их не видит (даже в devtools / сыром ответе на create)
    и не может задать через тело запроса. Себестоимость всегда считается
    динамически на бэкенде (cost_is_manual недоступен).
    """

    class Meta(SaleSerializer.Meta):
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
            "price_som",
            "paid_som",
            "date",
            "payment_date",
            "created_at",
        )
        read_only_fields = ("created_at",)
        extra_kwargs = {
            "price_som": {"required": False},
            "paid_som": {"required": False},
            "payment_date": {"required": False},
            "weight_kg": {"required": False},
        }


class ClientPriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientPrice
        fields = ("id", "client_code", "price_per_kg_som", "note", "updated_at")
        read_only_fields = ("updated_at",)

    def validate_client_code(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Укажите код клиента.")
        return value

    def validate_price_per_kg_som(self, value):
        if value <= 0:
            raise serializers.ValidationError("Цена за кг должна быть больше нуля.")
        return value
