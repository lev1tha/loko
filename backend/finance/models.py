from decimal import Decimal

from django.conf import settings as dj_settings
from django.db import models
from django.db.models import Sum

ONE = Decimal("1")


def _default(key: str) -> Decimal:
    return Decimal(dj_settings.LOKO_EXPRESS[key])


def kgs_of(amount, currency, rate) -> Decimal:
    """Перевести сумму в сом по СНАПШОТУ курса операции (CNY) или как есть (KGS).

    ``rate`` — курс юаня, зафиксированный на операции в момент ввода. Так история
    не «плывёт» при смене текущего курса в Настройках (см. снапшот в save()).
    """
    amount = amount or Decimal("0")
    if currency == Currency.CNY:
        return amount * (rate if rate is not None else ONE)
    return amount


def live_cny_rate() -> Decimal:
    return AppSettings.load().cny_to_kgs_rate


class Currency(models.TextChoices):
    KGS = "KGS", "Сом (KGS)"
    CNY = "CNY", "Юань (CNY)"


class Module(models.TextChoices):
    EXPRESS = "EXPRESS", "Loko Express"
    BUSINESS = "BUSINESS", "Loko Business"
    COMMON = "COMMON", "Общий"


class AppSettings(models.Model):
    """Singleton holding the editable business parameters.

    The dynamic cost price lives here so an administrator can change it at
    any time without a deployment. Pricing parameters are stored too so the
    whole Loko Express economy is configurable from one place.
    """

    base_cost_per_kg_som = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Себестоимость за 1 кг (сом)",
    )
    price_per_kg_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Цена за 1 кг ($)",
    )
    usd_rate_som = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Внутренний курс доллара (сом)",
    )
    # Loko Business: display rate for the сом/юань toggle (1 CNY = X KGS).
    cny_to_kgs_rate = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal("12.5"),
        verbose_name="Курс юаня для отображения (1 CNY = X сом)",
    )
    # Profit tax rate (%) — legacy single rate; kept for back-compat / overrides.
    profit_tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("10"),
        verbose_name="Ставка налога на прибыль (%)",
    )
    # Налог на прибыль до налогов по каналу оплаты (редактируемый).
    cash_tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("6"),
        verbose_name="Налог — наличные (%)",
    )
    noncash_tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("4"),
        verbose_name="Налог — безналичные (%)",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Настройки"
        verbose_name_plural = "Настройки"

    def __str__(self) -> str:
        return "Настройки Loko"

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce singleton
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "AppSettings":
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "base_cost_per_kg_som": _default("BASE_COST_PER_KG_SOM"),
                "price_per_kg_usd": _default("PRICE_PER_KG_USD"),
                "usd_rate_som": _default("USD_RATE_SOM"),
            },
        )
        return obj


class Account(models.Model):
    """A cashbox / bank account ("Касса / Счёт").

    * ``kind`` — cash vs. bank, drives the cash/non-cash split in reports.
    * ``currency`` — KGS or CNY (Loko Business uses CNY accounts).
    * ``module`` — which direction the account belongs to (Express / Business).
    """

    class Kind(models.TextChoices):
        CASH = "CASH", "Наличные"
        BANK = "BANK", "Банк (безналичный)"

    name = models.CharField(max_length=120, unique=True, verbose_name="Название")
    kind = models.CharField(
        max_length=10,
        choices=Kind.choices,
        default=Kind.CASH,
        verbose_name="Тип",
    )
    currency = models.CharField(
        max_length=3,
        choices=Currency.choices,
        default=Currency.KGS,
        verbose_name="Валюта",
    )
    module = models.CharField(
        max_length=10,
        choices=Module.choices,
        default=Module.EXPRESS,
        verbose_name="Направление",
    )
    initial_balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        verbose_name="Начальный остаток",
    )
    # Курс юаня, зафиксированный для начального остатка CNY-счёта (снапшот).
    initial_kgs_rate = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        verbose_name="Курс начального остатка (CNY)",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Счёт / Касса"
        verbose_name_plural = "Счета / Кассы"
        ordering = ("module", "name")

    def __str__(self) -> str:
        return f"{self.name} ({self.currency})"

    def save(self, *args, **kwargs):
        # Снапшот курса для начального остатка CNY-счёта (как у операций) — иначе
        # новый юаневый счёт считался бы 1:1 и ломал консолидацию/сверку.
        if self.currency == Currency.CNY:
            if self.initial_kgs_rate is None:
                self.initial_kgs_rate = live_cny_rate()
        else:
            self.initial_kgs_rate = None
        super().save(*args, **kwargs)

    @property
    def is_cash(self) -> bool:
        return self.kind == self.Kind.CASH

    # --- balance components (all in the account's own currency) -------------
    def income_total(self) -> Decimal:
        # Cash actually received from sales (paid_som), not the accrued amount.
        agg = self.sales.aggregate(s=Sum("paid_som"))["s"] if hasattr(self, "sales") else None
        return agg or Decimal("0")

    def deposit_total(self) -> Decimal:
        # Business deposits physically received into this account.
        if not hasattr(self, "deposits"):
            return Decimal("0")
        agg = self.deposits.aggregate(s=Sum("amount"))["s"]
        return agg or Decimal("0")

    def expense_total(self) -> Decimal:
        # Cash actually paid out (paid_amount), not the accrued amount.
        agg = self.expenses.aggregate(s=Sum("paid_amount"))["s"]
        return agg or Decimal("0")

    def transfers_in_total(self) -> Decimal:
        # Credited amount (to_amount handles currency conversion).
        agg = self.incoming_transfers.aggregate(s=Sum("to_amount"))["s"]
        return agg or Decimal("0")

    def transfers_out_total(self) -> Decimal:
        agg = self.outgoing_transfers.aggregate(s=Sum("amount"))["s"]
        return agg or Decimal("0")

    @property
    def current_balance(self) -> Decimal:
        """Начальный + Доходы + Депозиты − Расходы +/− Перемещения (в валюте счёта)."""
        return (
            self.initial_balance
            + self.income_total()
            + self.deposit_total()
            - self.expense_total()
            + self.transfers_in_total()
            - self.transfers_out_total()
        )

    @property
    def balance_kgs(self) -> Decimal:
        """Текущий остаток в сомах по СНАПШОТ-курсам операций (история не плывёт).

        Для KGS-счёта совпадает с current_balance; для CNY каждая компонента
        переводится по своему зафиксированному курсу.
        """
        if self.currency != Currency.CNY:
            return self.current_balance
        total = self.initial_balance * (self.initial_kgs_rate or ONE)
        # Продажи (Express) всегда в сомах — но на CNY-счёте их обычно нет.
        total += self.income_total()
        for d in self.deposits.all():
            total += d.kgs_value
        for e in self.expenses.all():
            total -= e.kgs_paid
        for t in self.incoming_transfers.select_related("to_account", "from_account"):
            total += t.kgs_in
        for t in self.outgoing_transfers.select_related("to_account", "from_account"):
            total -= t.kgs_out
        return total


class OpexArticle(models.TextChoices):
    """Operating-expense articles (sub-categories of OpEx)."""

    RENT = "RENT", "Аренда"
    PAYROLL = "PAYROLL", "ФОТ (Фонд оплаты труда)"
    INCOME_TAX = "INCOME_TAX", "Подоходный налог"
    SOCIAL_FUND = "SOCIAL_FUND", "Соц.фонд"
    OTHER = "OTHER", "Прочие расходы"


class ExpenseCategory(models.TextChoices):
    """Expense kinds and how they influence the two financial reports.

    OPEX      — operating expenses: affect both P&L (ООПИУ) and Cash Flow (ОДДС).
                Requires an ``opex_article`` (Аренда / ФОТ / Подоходный / Соцфонд /
                Прочие). For «Прочие расходы» the comment is mandatory.
    SUPPLIER  — payments to suppliers: affect Cash Flow and reduce payables.
    OTHER     — non-operating activity.
    OWNER     — owner withdrawal: Cash Flow only, reduces the cash balance.
    """

    OPEX = "OPEX", "Операционные расходы (OpEx)"
    COGS = "COGS", "Себестоимость / закуп товара"
    SUPPLIER = "SUPPLIER", "Оплата / аванс поставщику"
    OTHER = "OTHER", "Неоперационная деятельность (Другое)"
    OWNER = "OWNER", "Изъятие собственника"
    INVEST = "INVEST", "Инвестиционная (оборудование/активы)"
    FINANCING = "FINANCING", "Финансовая (кредиты/проценты)"


class Expense(models.Model):
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="expenses",
        verbose_name="Счёт списания",
    )
    category = models.CharField(
        max_length=12,
        choices=ExpenseCategory.choices,
        verbose_name="Категория",
    )
    opex_article = models.CharField(
        max_length=12,
        choices=OpexArticle.choices,
        blank=True,
        null=True,
        verbose_name="Статья OpEx",
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, verbose_name="Сумма начисления"
    )
    paid_amount = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True, verbose_name="Сумма оплаты"
    )
    # Курс юаня, зафиксированный на момент ввода (только для CNY-счёта).
    kgs_rate = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True, verbose_name="Курс юаня (снапшот)"
    )
    description = models.CharField(max_length=500, blank=True, verbose_name="Комментарий")
    date = models.DateField(verbose_name="Дата операции")
    payment_date = models.DateField(null=True, blank=True, verbose_name="Дата оплаты")
    created_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expenses",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Расход"
        verbose_name_plural = "Расходы"
        ordering = ("-date", "-id")

    @property
    def payable(self) -> Decimal:
        """Кредиторка по расходу = начисление − оплата."""
        return (self.amount or Decimal("0")) - (self.paid_amount or Decimal("0"))

    @property
    def _currency(self) -> str:
        return self.account.currency

    @property
    def kgs_amount(self) -> Decimal:
        """Начисление в сомах по снапшот-курсу."""
        return kgs_of(self.amount, self._currency, self.kgs_rate)

    @property
    def kgs_paid(self) -> Decimal:
        """Оплата в сомах по снапшот-курсу."""
        return kgs_of(self.paid_amount, self._currency, self.kgs_rate)

    @property
    def kgs_payable(self) -> Decimal:
        return kgs_of(self.payable, self._currency, self.kgs_rate)

    def save(self, *args, **kwargs):
        # Payment defaults: fully paid on the same day unless specified.
        if self.paid_amount in (None, ""):
            self.paid_amount = self.amount
        if self.payment_date in (None, ""):
            self.payment_date = self.date
        # Снапшот курса юаня для CNY-счёта (история не плывёт при смене курса).
        if self.account_id and self.account.currency == Currency.CNY:
            if self.kgs_rate is None:
                self.kgs_rate = live_cny_rate()
        else:
            self.kgs_rate = None
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.get_category_display()} — {self.amount}"


class Transfer(models.Model):
    """Internal movement of money between two accounts.

    Supports currency conversion: ``amount`` is debited from ``from_account``
    in its currency, ``to_amount`` is credited to ``to_account`` in its
    currency, and ``rate`` is the manually-entered exchange rate used
    (e.g. KGS per CNY when buying yuan from MBank).
    """

    from_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="outgoing_transfers",
        verbose_name="Со счёта",
    )
    to_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="incoming_transfers",
        verbose_name="На счёт",
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, verbose_name="Сумма списания"
    )
    to_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        verbose_name="Сумма зачисления",
    )
    rate = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("1"),
        verbose_name="Курс обмена",
    )
    # Курс юаня для консолидации в сом (снапшот), если в переводе участвует CNY-счёт.
    kgs_rate = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True, verbose_name="Курс юаня (снапшот)"
    )
    description = models.CharField(max_length=255, blank=True, verbose_name="Комментарий")
    date = models.DateField(verbose_name="Дата")
    created_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transfers",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Перемещение"
        verbose_name_plural = "Перемещения"
        ordering = ("-date", "-id")

    @property
    def is_conversion(self) -> bool:
        return self.from_account.currency != self.to_account.currency

    @property
    def kgs_out(self) -> Decimal:
        """Сомовый эквивалент списания со счёта-источника (по снапшот-курсу)."""
        return kgs_of(self.amount, self.from_account.currency, self.kgs_rate)

    @property
    def kgs_in(self) -> Decimal:
        """Сомовый эквивалент зачисления на счёт-получатель (по снапшот-курсу)."""
        return kgs_of(self.to_amount, self.to_account.currency, self.kgs_rate)

    def save(self, *args, **kwargs):
        # Снапшот курса юаня, если в переводе участвует CNY-счёт.
        if self.from_account_id and self.to_account_id:
            has_cny = Currency.CNY in (self.from_account.currency, self.to_account.currency)
            if has_cny and self.kgs_rate is None:
                self.kgs_rate = live_cny_rate()
            elif not has_cny:
                self.kgs_rate = None
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.from_account} → {self.to_account}: {self.amount}"
