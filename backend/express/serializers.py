from decimal import Decimal

from django.db.models import Sum
from rest_framework import serializers

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field

from finance.models import Account, Branch
from .models import Client, ClientPrice, Sale, WarehouseItem, WarehouseOrder


class SaleSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source="account.name", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, default=None)
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
            "branch",
            "branch_name",
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
            "branch": {"required": False},
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

        # Филиал НЕ обязателен: если не выбран — сервер подставит филиал по умолчанию
        # (Гульчинская) в perform_create. Историю (branch=NULL) правим без филиала.

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
    """Узкий сериализатор продаж для не-финансовых ролей (без себестоимости/маржи).

    Оставлен для обратной совместимости ``SaleViewSet``. В двухэтапном учёте
    оператор продажи напрямую НЕ создаёт — он формирует складскую заявку
    (``WarehouseOrder`` + ``WarehouseItem``), а продажа рождается при оприходовании.
    """

    class Meta(SaleSerializer.Meta):
        fields = (
            "id", "client_code", "amount_mode", "amount_mode_display",
            "weight_kg", "places", "account", "account_name", "branch_name",
            "is_cash", "price_som", "paid_som", "date", "payment_date", "created_at",
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


class WarehouseItemSerializer(serializers.ModelSerializer):
    """Позиция заявки — один код с его статусом (для доски склада и «Мои продажи»).

    ``price_som`` берётся с созданной при оприходовании продажи (иначе ``None``) —
    финансовые цифры показываем только когда позиция реально найдена (FOUND)."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    order_id = serializers.IntegerField(source="order.id", read_only=True)
    branch_name = serializers.CharField(source="order.branch.name", read_only=True, default=None)
    created_by_name = serializers.CharField(source="order.created_by.username", read_only=True, default=None)
    price_som = serializers.SerializerMethodField()

    class Meta:
        model = WarehouseItem
        fields = (
            "id", "order_id", "client_code", "status", "status_display",
            "weight_kg", "price_som", "reason", "branch_name", "created_by_name",
            "created_at", "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_price_som(self, obj):
        # Строкой — как остальные денежные поля DRF (coerce_to_string), None у ненайденных.
        return str(obj.sale.price_som) if obj.sale_id else None


class WarehouseOrderSerializer(serializers.ModelSerializer):
    """Заявка-«чек» на сборку. Оператор/менеджер создаёт её с кодами (без денег);
    позиции (``items``) ведёт складовщик пошту́чно. Статус позиции — на позиции."""

    branch_name = serializers.CharField(source="branch.name", read_only=True, default=None)
    created_by_name = serializers.CharField(source="created_by.username", read_only=True, default=None)
    assigned_to_name = serializers.CharField(source="assigned_to.username", read_only=True, default=None)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    items = WarehouseItemSerializer(many=True, read_only=True)

    class Meta:
        model = WarehouseOrder
        fields = (
            "id", "branch", "branch_name", "created_by", "created_by_name",
            "assigned_to", "assigned_to_name", "status", "status_display",
            "client_codes", "items", "comment", "created_at", "updated_at",
        )
        read_only_fields = (
            "created_by", "assigned_to", "status", "created_at", "updated_at",
        )
        extra_kwargs = {
            # Филиал: у оператора/складовщика подставляется на сервере (perform_create).
            "branch": {"required": False},
        }

    def validate_client_codes(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Коды клиентов должны быть списком.")
        codes = [str(c).strip() for c in value if str(c).strip()]
        if not (1 <= len(codes) <= WarehouseOrder.MAX_CODES):
            raise serializers.ValidationError(
                f"Укажите от 1 до {WarehouseOrder.MAX_CODES} кодов клиентов."
            )
        return codes


class WarehouseStatusSerializer(serializers.Serializer):
    """Смена статуса заявки (складовщик/кассир). Валидация перехода — во вьюсете."""

    status = serializers.ChoiceField(choices=WarehouseOrder.Status.choices)
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class WarehouseReceiveSerializer(serializers.Serializer):
    """Оприходование позиции складовщиком: фактический вес + счёт зачисления."""

    weight_kg = serializers.DecimalField(
        max_digits=10, decimal_places=3, min_value=Decimal("0.001"),
    )
    account = serializers.PrimaryKeyRelatedField(
        queryset=Account.objects.filter(module="EXPRESS", currency="KGS", is_active=True),
    )


class WarehouseNotFoundSerializer(serializers.Serializer):
    """Позиция не найдена — обязательна причина (куда смотрели / чего нет)."""

    reason = serializers.CharField()

    def validate_reason(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Укажите причину — что не найдено.")
        return value


class ClientSerializer(serializers.ModelSerializer):
    """Клиент для CRM админа: имя, телефон и агрегаты (заказов, кг, сумма)."""

    orders_count = serializers.SerializerMethodField()
    total_kg = serializers.SerializerMethodField()
    total_som = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = ("id", "phone", "name", "created_at", "orders_count", "total_kg", "total_som")

    def _found(self, obj):
        return WarehouseItem.objects.filter(
            order__client=obj,
            status__in=[WarehouseItem.Status.FOUND, WarehouseItem.Status.DELIVERED],
        )

    def _agg(self, obj, field, places):
        v = self._found(obj).aggregate(s=Sum(field))["s"] or Decimal("0")
        return str(Decimal(str(v)).quantize(places))

    @extend_schema_field(OpenApiTypes.INT)
    def get_orders_count(self, obj):
        return obj.orders.count()

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_total_kg(self, obj):
        return self._agg(obj, "weight_kg", Decimal("0.001"))

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_total_som(self, obj):
        return self._agg(obj, "sale__price_som", Decimal("0.01"))


class PublicIntakeSerializer(serializers.Serializer):
    """Самозапись клиента по QR: филиал + телефон + имя + коды (публично, без входа)."""

    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True))
    phone = serializers.CharField(max_length=32)
    name = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")
    client_codes = serializers.ListField(child=serializers.CharField(), allow_empty=False)

    def validate_phone(self, value):
        if len(Client.normalize_phone(value)) < 6:
            raise serializers.ValidationError("Укажите корректный номер телефона.")
        return value

    def validate_client_codes(self, value):
        codes = []
        for c in value:
            c = str(c).strip()
            if c and c not in codes:
                codes.append(c)
        if not (1 <= len(codes) <= WarehouseOrder.MAX_CODES):
            raise serializers.ValidationError(
                f"Укажите от 1 до {WarehouseOrder.MAX_CODES} кодов клиента."
            )
        return codes


class PublicRateSerializer(serializers.Serializer):
    """Клиент ставит звёзды сотруднику (публично, по телефону). 1–5."""

    phone = serializers.CharField(max_length=32)
    employee = serializers.IntegerField()
    stars = serializers.IntegerField(min_value=1, max_value=5)
