from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import (
    Account, AppSettings, Currency, Expense, ExpenseArticle, ExpenseCategory,
    FINANCING_ARTICLES, INVESTING_ARTICLES, OPERATING_ARTICLES, OtherIncome, Transfer,
)

_KGS_FIELD = serializers.DecimalField(max_digits=16, decimal_places=2)


class AppSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppSettings
        fields = (
            "base_cost_per_kg_som",
            "price_per_kg_usd",
            "usd_rate_som",
            "cny_to_kgs_rate",
            "profit_tax_rate",
            "cash_tax_rate",
            "noncash_tax_rate",
            "updated_at",
        )
        read_only_fields = ("updated_at",)


class AccountSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    currency_display = serializers.CharField(source="get_currency_display", read_only=True)
    module_display = serializers.CharField(source="get_module_display", read_only=True)
    current_balance = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    current_balance_kgs = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = Account
        fields = (
            "id",
            "name",
            "kind",
            "kind_display",
            "currency",
            "currency_display",
            "module",
            "module_display",
            "initial_balance",
            "is_active",
            "current_balance",
            "current_balance_kgs",
            "created_at",
        )
        read_only_fields = ("created_at",)


class ExpenseSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source="get_category_display", read_only=True)
    opex_article_display = serializers.CharField(
        source="get_opex_article_display", read_only=True, default=None
    )
    account_name = serializers.CharField(source="account.name", read_only=True)
    account_currency = serializers.CharField(source="account.currency", read_only=True)
    payable = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    # Суммы, приведённые к сому по СНАПШОТ-курсу операции (юань × зафикс. курс).
    amount_kgs = serializers.SerializerMethodField()
    paid_amount_kgs = serializers.SerializerMethodField()
    payable_kgs = serializers.SerializerMethodField()

    @extend_schema_field(_KGS_FIELD)
    def get_amount_kgs(self, obj):
        return obj.kgs_amount

    @extend_schema_field(_KGS_FIELD)
    def get_paid_amount_kgs(self, obj):
        return obj.kgs_paid

    @extend_schema_field(_KGS_FIELD)
    def get_payable_kgs(self, obj):
        return obj.kgs_payable

    class Meta:
        model = Expense
        fields = (
            "id",
            "account",
            "account_name",
            "account_currency",
            "category",
            "category_display",
            "opex_article",
            "opex_article_display",
            "amount",          # начисление (в валюте счёта)
            "paid_amount",     # оплата (в валюте счёта)
            "payable",         # кредиторка (в валюте счёта)
            "amount_kgs",      # начисление в сомах (юань × курс)
            "paid_amount_kgs", # оплата в сомах
            "payable_kgs",     # кредиторка в сомах
            "description",
            "date",            # дата операции (ОПиУ)
            "payment_date",    # дата оплаты (ОДДС)
            "created_at",
        )
        read_only_fields = ("created_at",)
        extra_kwargs = {
            "paid_amount": {"required": False},
            "payment_date": {"required": False},
        }

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Сумма должна быть больше нуля.")
        return value

    def validate(self, attrs):
        category = attrs.get("category", getattr(self.instance, "category", None))
        article = attrs.get("opex_article", getattr(self.instance, "opex_article", None))
        description = attrs.get("description", getattr(self.instance, "description", ""))

        # Оплата в пределах начисления: 0 ≤ оплачено ≤ начислено.
        # Берём оплату из тела ИЛИ из объекта — чтобы PATCH, снижающий только
        # «начисление», не проскочил мимо проверки и не дал отрицательную кредиторку.
        amount = attrs.get("amount", getattr(self.instance, "amount", None))
        paid = attrs.get("paid_amount", None)
        if paid is None and self.instance is not None:
            paid = self.instance.paid_amount
        if paid is not None:
            if paid < 0:
                raise serializers.ValidationError({"paid_amount": "Оплата не может быть отрицательной."})
            if amount is not None and paid > amount:
                raise serializers.ValidationError(
                    {"paid_amount": "Оплата не может превышать сумму начисления."}
                )

        valid_by_cat = {
            ExpenseCategory.OPEX: OPERATING_ARTICLES,
            ExpenseCategory.INVEST: INVESTING_ARTICLES,
            ExpenseCategory.FINANCING: FINANCING_ARTICLES,
        }
        if category in valid_by_cat:
            if not article:
                raise serializers.ValidationError(
                    {"opex_article": "Выберите статью расхода."}
                )
            if article not in valid_by_cat[category]:
                raise serializers.ValidationError(
                    {"opex_article": "Статья не соответствует выбранной категории."}
                )
            # «Прочие расходы» → комментарий строго обязателен.
            if article == ExpenseArticle.OTHER and not (description or "").strip():
                raise serializers.ValidationError(
                    {"description": "Для «Прочих расходов» комментарий обязателен."}
                )
        else:
            # Категории без детализации (Себест./Поставщик/Изъятие/Другое).
            attrs["opex_article"] = None
        return attrs


class TransferSerializer(serializers.ModelSerializer):
    from_account_name = serializers.CharField(source="from_account.name", read_only=True)
    to_account_name = serializers.CharField(source="to_account.name", read_only=True)
    from_currency = serializers.CharField(source="from_account.currency", read_only=True)
    to_currency = serializers.CharField(source="to_account.currency", read_only=True)
    is_conversion = serializers.BooleanField(read_only=True)

    class Meta:
        model = Transfer
        fields = (
            "id",
            "from_account",
            "from_account_name",
            "from_currency",
            "to_account",
            "to_account_name",
            "to_currency",
            "amount",
            "to_amount",
            "rate",
            "is_conversion",
            "description",
            "date",
            "created_at",
        )
        read_only_fields = ("created_at",)
        extra_kwargs = {
            "to_amount": {"required": False},
            "rate": {"required": False},
        }

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Сумма должна быть больше нуля.")
        return value

    def validate(self, attrs):
        inst = self.instance
        # На частичном обновлении недостающие поля берём из объекта (а не как «пусто»),
        # иначе курс/зачисление молча обнулялись и портили остаток.
        src = attrs.get("from_account", getattr(inst, "from_account", None))
        dst = attrs.get("to_account", getattr(inst, "to_account", None))
        if src and dst and src == dst:
            raise serializers.ValidationError(
                "Счёт отправителя и получателя не могут совпадать."
            )
        amount = attrs.get("amount", getattr(inst, "amount", None))
        cross = bool(src and dst and src.currency != dst.currency)

        rate = attrs.get("rate", None)
        if rate in (None, ""):
            rate = getattr(inst, "rate", None)
        if cross and (rate in (None, "") or rate <= 0):
            raise serializers.ValidationError(
                {"rate": "Для конвертации укажите курс обмена (сом за 1 юань) больше нуля."}
            )
        if rate in (None, ""):
            rate = Decimal("1")
        attrs["rate"] = rate

        amount_or_rate_changed = "amount" in attrs or "rate" in attrs
        to_amount = attrs.get("to_amount", None)
        if to_amount in (None, ""):
            if inst is not None and not amount_or_rate_changed:
                # Правка только описания и т.п. — сохраняем явно заданное зачисление.
                attrs["to_amount"] = inst.to_amount
            elif not cross:
                attrs["to_amount"] = amount
            elif src.currency == Currency.KGS and dst.currency == Currency.CNY:
                # сом → юань: юань = сом ÷ курс (курс = сом за 1 юань).
                attrs["to_amount"] = (amount / rate).quantize(Decimal("0.01"))
            else:
                # юань → сом: сом = юань × курс.
                attrs["to_amount"] = (amount * rate).quantize(Decimal("0.01"))
        if attrs.get("to_amount") is not None and attrs["to_amount"] <= 0:
            raise serializers.ValidationError({"to_amount": "Сумма зачисления должна быть больше нуля."})
        return attrs


class OtherIncomeSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source="account.name", read_only=True)
    account_currency = serializers.CharField(source="account.currency", read_only=True)
    amount_kgs = serializers.SerializerMethodField()

    @extend_schema_field(_KGS_FIELD)
    def get_amount_kgs(self, obj):
        return obj.kgs_amount

    class Meta:
        model = OtherIncome
        fields = (
            "id", "account", "account_name", "account_currency",
            "amount", "amount_kgs", "description", "date", "created_at",
        )
        read_only_fields = ("created_at",)

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Сумма должна быть больше нуля.")
        return value
