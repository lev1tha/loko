from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings as dj_settings
from django.db import models

from finance.models import Account, AppSettings

TWO_PLACES = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


class Sale(models.Model):
    """A Loko Express cargo sale.

    Two amount modes (matches how the real ledger is kept):
      * WEIGHT — price computed as ``weight * price_per_kg_usd * usd_rate_som``.
      * DIRECT — the sum is entered manually (``price_som``), weight optional;
        this mirrors the real «Сумма начисления» column.

    Accrual vs. cash (как в реальном учёте):
      * ``price_som``    — сумма начисления → выручка (ОПиУ), по ``date``.
      * ``paid_som``     — сумма оплаты → приток (ОДДС) и баланс, по ``payment_date``.
      * ``receivable_som`` (= начисление − оплата) — дебиторка по продаже.
    """

    class AmountMode(models.TextChoices):
        WEIGHT = "WEIGHT", "По весу (3$ × курс)"
        DIRECT = "DIRECT", "Прямая сумма"

    client_code = models.CharField(
        max_length=120,
        verbose_name="Код клиента",
        help_text="Главный идентификатор клиента/товара (номер или код)",
    )
    amount_mode = models.CharField(
        max_length=8,
        choices=AmountMode.choices,
        default=AmountMode.WEIGHT,
        verbose_name="Режим суммы",
    )
    weight_kg = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name="Вес (кг)",
        help_text="Дробные значения, напр. 0.80, 0.53. Необязателен в режиме «прямая сумма».",
    )
    places = models.PositiveIntegerField(default=1, verbose_name="Количество мест")

    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="sales",
        verbose_name="Счёт зачисления",
        help_text="Касса/банк, куда поступила оплата (нал/безнал)",
    )

    # --- snapshotted pricing parameters ------------------------------------
    price_per_kg_usd = models.DecimalField(max_digits=10, decimal_places=2)
    usd_rate_som = models.DecimalField(max_digits=10, decimal_places=2)
    cost_per_kg_som = models.DecimalField(max_digits=10, decimal_places=2)

    # --- computed / stored amounts -----------------------------------------
    price_som = models.DecimalField(
        max_digits=14, decimal_places=2, verbose_name="Сумма начисления (сом)"
    )
    paid_som = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True, verbose_name="Сумма оплаты (сом)"
    )
    cost_som = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0"), verbose_name="Себестоимость (сом)"
    )
    margin_som = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0"), verbose_name="Маржа (сом)"
    )
    cost_is_manual = models.BooleanField(
        default=False, verbose_name="Себестоимость введена вручную"
    )

    date = models.DateField(verbose_name="Дата операции")
    payment_date = models.DateField(null=True, blank=True, verbose_name="Дата оплаты")
    created_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Продажа"
        verbose_name_plural = "Продажи"
        ordering = ("-date", "-id")

    def __str__(self) -> str:
        return f"{self.client_code} — {self.price_som} сом"

    @property
    def is_cash(self) -> bool:
        return self.account.is_cash

    @property
    def receivable_som(self) -> Decimal:
        """Дебиторка по продаже = начисление − оплата."""
        return (self.price_som or Decimal("0")) - (self.paid_som or Decimal("0"))

    def _apply_pricing(self):
        """Fill snapshot params, compute price/cost/margin per amount mode."""
        cfg = AppSettings.load()
        if self.price_per_kg_usd in (None, ""):
            self.price_per_kg_usd = cfg.price_per_kg_usd
        if self.usd_rate_som in (None, ""):
            self.usd_rate_som = cfg.usd_rate_som
        if self.cost_per_kg_som in (None, ""):
            self.cost_per_kg_som = cfg.base_cost_per_kg_som

        weight = Decimal(self.weight_kg) if self.weight_kg not in (None, "") else Decimal("0")

        if self.amount_mode == self.AmountMode.WEIGHT:
            # Price from weight (0 if weight omitted — вес необязателен).
            self.price_som = _money(weight * self.price_per_kg_usd * self.usd_rate_som)
        else:
            # DIRECT: price_som comes from input.
            self.price_som = _money(Decimal(self.price_som or 0))

        # Cost: manual override (вписанная себестоимость) or dynamic from weight.
        if self.cost_is_manual:
            self.cost_som = _money(Decimal(self.cost_som or 0))
        else:
            self.cost_som = _money(weight * self.cost_per_kg_som)

        self.margin_som = self.price_som - self.cost_som

        # Payment defaults: fully paid on the same day unless specified.
        if self.paid_som in (None, ""):
            self.paid_som = self.price_som
        if self.payment_date in (None, ""):
            self.payment_date = self.date

    def save(self, *args, **kwargs):
        self._apply_pricing()
        super().save(*args, **kwargs)
