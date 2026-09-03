"""Сериализаторы /api/kargo/ — контракт для PHP-фасада kargoosh.kg."""
from decimal import Decimal

from rest_framework import serializers

from finance.models import Account, Branch
from .models import Client, DeliveryStatus, Sale

# Числовые статусы Kargo (orders.i_status) ↔ статусы Loko.
STATUS_CODE = {DeliveryStatus.TRANSIT: 1, DeliveryStatus.ARRIVED: 2, DeliveryStatus.DELIVERED: 3}
CODE_STATUS = {v: k for k, v in STATUS_CODE.items()}


def parse_status(raw):
    """«1|2|3» или «TRANSIT|ARRIVED|DELIVERED» → DeliveryStatus, иначе None."""
    if raw in (None, ""):
        return None
    raw = str(raw).strip().upper()
    if raw.isdigit():
        return CODE_STATUS.get(int(raw))
    return raw if raw in DeliveryStatus.values else None


def _branch_field(required=False):
    return serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.filter(is_active=True), required=required, allow_null=not required,
    )


class _RegionMixin:
    """``branch`` (id) или ``region`` (строка Kargo, напр. «Ош») → филиал."""

    def resolve_branch(self, data):
        b = data.get("branch")
        if b is None and data.get("region"):
            b = Branch.objects.filter(legacy_kargo_region=data["region"].strip(), is_active=True).first()
            if b is None:
                raise serializers.ValidationError({"region": "Неизвестный регион Kargo."})
        return b


class ClientOutSerializer(serializers.ModelSerializer):
    """Профиль клиента для PHP (без хеша пароля и служебных полей)."""

    branch_name = serializers.CharField(source="branch.name", read_only=True, default="")
    region = serializers.CharField(source="branch.legacy_kargo_region", read_only=True, default="")

    class Meta:
        model = Client
        fields = (
            "id", "code", "name", "last_name", "phone", "email", "tg_id", "discount",
            "branch", "branch_name", "region", "is_enabled", "reg_date", "access_date",
        )
        read_only_fields = fields


class LoginSerializer(serializers.Serializer):
    login = serializers.CharField(max_length=160, help_text="E-mail или телефон")
    password = serializers.CharField(max_length=128, trim_whitespace=False)


class RegisterSerializer(_RegionMixin, serializers.Serializer):
    name = serializers.CharField(max_length=160, min_length=3)
    last_name = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=32)
    email = serializers.EmailField(max_length=160)
    password = serializers.CharField(min_length=6, max_length=128, trim_whitespace=False)
    branch = _branch_field()
    region = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")

    def validate_phone(self, value):
        if len(Client.normalize_phone(value)) < 9:
            raise serializers.ValidationError("Укажите корректный номер телефона.")
        return value

    def validate(self, data):
        data["branch"] = self.resolve_branch(data)
        if data["branch"] is None:
            raise serializers.ValidationError({"branch": "Выберите карго (филиал)."})
        return data


class ChangePasswordSerializer(serializers.Serializer):
    client_id = serializers.IntegerField()
    current_password = serializers.CharField(max_length=128, trim_whitespace=False)
    new_password = serializers.CharField(min_length=6, max_length=128, trim_whitespace=False)


class RecoverySerializer(serializers.Serializer):
    login = serializers.CharField(max_length=160, help_text="E-mail или телефон")
    code = serializers.CharField(max_length=32, help_text="Код клиента (проверка личности, как в PHP)")


class ResetPasswordSerializer(serializers.Serializer):
    pass_code = serializers.CharField(max_length=100)
    password = serializers.CharField(min_length=6, max_length=128, trim_whitespace=False)


class ClientUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160, min_length=3, required=False)
    last_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=32, required=False)
    email = serializers.EmailField(max_length=160, required=False)
    code = serializers.CharField(max_length=32, min_length=5, required=False)
    tg_id = serializers.CharField(max_length=100, required=False, allow_blank=True)


class KargoOrderSerializer(serializers.ModelSerializer):
    """Заказ в терминах Kargo: трек, статус (1/2/3), даты, вес, сумма."""

    status = serializers.CharField(source="delivery_status", read_only=True)
    status_code = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_delivery_status_display", read_only=True)
    pickup_date = serializers.SerializerMethodField()
    branch_name = serializers.CharField(source="branch.name", read_only=True, default="")

    class Meta:
        model = Sale
        fields = (
            "id", "tracking_number", "client_code", "status", "status_code", "status_label",
            "shipment_date", "arrival_date", "pickup_date", "weight_kg", "places",
            "price_som", "paid_som", "branch", "branch_name", "legacy_kargo_id",
        )
        read_only_fields = fields

    def get_status_code(self, obj) -> int:
        return STATUS_CODE.get(obj.delivery_status, 3)

    def get_pickup_date(self, obj):
        return obj.payment_date if obj.delivery_status == DeliveryStatus.DELIVERED else None


class ShipmentItemSerializer(serializers.Serializer):
    tracking_number = serializers.CharField(max_length=120)
    client_code = serializers.CharField(max_length=120)
    shipment_date = serializers.DateField(required=False, allow_null=True)


class ShipmentsSerializer(_RegionMixin, serializers.Serializer):
    """Пакет «отправлено из Китая» (импорт Excel / ручное добавление в PHP-админке)."""

    branch = _branch_field()
    region = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    shipment_date = serializers.DateField(required=False, allow_null=True)
    items = ShipmentItemSerializer(many=True, allow_empty=False, max_length=2000)

    def validate(self, data):
        data["branch"] = self.resolve_branch(data)
        return data


class ArriveSerializer(_RegionMixin, serializers.Serializer):
    """«Поступил на склад»: клиент + трек-номера + вес (add_post в PHP)."""

    client_code = serializers.CharField(max_length=120, min_length=5)
    tracking_numbers = serializers.ListField(child=serializers.CharField(max_length=120), allow_empty=False, max_length=200)
    weight_kg = serializers.DecimalField(max_digits=10, decimal_places=3, min_value=Decimal("0"))
    branch = _branch_field()
    region = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    account = serializers.PrimaryKeyRelatedField(queryset=Account.objects.filter(is_active=True), required=False, allow_null=True)

    def validate_tracking_numbers(self, value):
        out = []
        for t in value:
            t = t.strip()
            if t and t not in out:
                out.append(t)
        if not out:
            raise serializers.ValidationError("Укажите трек-номер.")
        return out

    def validate(self, data):
        data["branch"] = self.resolve_branch(data)
        return data


class PickupSerializer(serializers.Serializer):
    """«Отдан клиенту»: все заказы кода со склада за дату прибытия, оплата на счёт."""

    client_code = serializers.CharField(max_length=120)
    arrival_date = serializers.DateField()
    account = serializers.PrimaryKeyRelatedField(queryset=Account.objects.filter(is_active=True))
    pickup_date = serializers.DateField(required=False, allow_null=True)
