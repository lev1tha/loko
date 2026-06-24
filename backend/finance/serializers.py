from decimal import Decimal

from rest_framework import serializers

from .models import Account, AppSettings, Expense, ExpenseCategory, OpexArticle, Transfer


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
            "created_at",
        )
        read_only_fields = ("created_at",)


class ExpenseSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source="get_category_display", read_only=True)
    opex_article_display = serializers.CharField(
        source="get_opex_article_display", read_only=True, default=None
    )
    account_name = serializers.CharField(source="account.name", read_only=True)
    payable = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Expense
        fields = (
            "id",
            "account",
            "account_name",
            "category",
            "category_display",
            "opex_article",
            "opex_article_display",
            "amount",          # начисление
            "paid_amount",     # оплата
            "payable",         # кредиторка
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

        if category == ExpenseCategory.OPEX:
            if not article:
                raise serializers.ValidationError(
                    {"opex_article": "Для операционного расхода выберите статью."}
                )
            # «Прочие расходы» → комментарий строго обязателен.
            if article == OpexArticle.OTHER and not (description or "").strip():
                raise serializers.ValidationError(
                    {"description": "Для «Прочих расходов» комментарий обязателен."}
                )
        else:
            # Article only applies to OpEx.
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
        src = attrs.get("from_account")
        dst = attrs.get("to_account")
        if src and dst and src == dst:
            raise serializers.ValidationError(
                "Счёт отправителя и получателя не могут совпадать."
            )
        amount = attrs.get("amount")
        to_amount = attrs.get("to_amount")
        rate = attrs.get("rate")

        same_currency = src and dst and src.currency == dst.currency
        if to_amount in (None, ""):
            attrs["to_amount"] = amount if same_currency else (amount * (rate or Decimal("1")))
        if rate in (None, ""):
            attrs["rate"] = Decimal("1")
        if attrs.get("to_amount") is not None and attrs["to_amount"] <= 0:
            raise serializers.ValidationError({"to_amount": "Сумма зачисления должна быть больше нуля."})
        return attrs
