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

    @property
    def est_weight_kg(self) -> Decimal | None:
        """Расчётный («предположительный») вес для показа админу.

        Если вес задан — возвращаем его. В режиме «прямая сумма» вес не хранится,
        поэтому выводим его из суммы: цена ÷ (цена_за_кг_$ × курс_$). Округляем до
        2 знаков (как просили для отображения)."""
        if self.weight_kg is not None:
            return self.weight_kg.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        rate = (self.price_per_kg_usd or Decimal("0")) * (self.usd_rate_som or Decimal("0"))
        if rate > 0 and self.price_som:
            return (self.price_som / rate).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        return None

    def _client_unit_price(self):
        """Спец-цена за 1 кг (сом) для этого клиента, если задана; иначе None.

        Позволяет «по весу» считать сумму по индивидуальной цене клиента (250/220
        вместо 270) — в т.ч. для сотрудника, который саму цену не видит."""
        if not self.client_code:
            return None
        return (
            ClientPrice.objects.filter(client_code=self.client_code)
            .values_list("price_per_kg_som", flat=True)
            .first()
        )

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
            # Цена за кг: спец-цена клиента (если есть), иначе цена по умолчанию
            # (цена_за_кг_$ × курс). Сумма (0, если вес не указан — вес необязателен).
            unit = self._client_unit_price()
            if unit is not None:
                self.price_som = _money(weight * unit)
            else:
                self.price_som = _money(weight * self.price_per_kg_usd * self.usd_rate_som)
            cost_weight = weight
        else:
            # DIRECT: price_som comes from input.
            self.price_som = _money(Decimal(self.price_som or 0))
            # Если вес не задан — выводим РАСЧЁТНЫЙ вес из суммы (сумма ÷ ставка-за-кг)
            # ТОЛЬКО для расчёта себестоимости. В поле weight_kg его НЕ пишем: его
            # разрядность меньше (overflow на крупных суммах), и хранить «искусственный»
            # вес незачем — экономика остаётся единой с продажами «по весу».
            cost_weight = weight
            if cost_weight <= 0:
                price_rate = self.price_per_kg_usd * self.usd_rate_som
                if price_rate > 0:
                    cost_weight = self.price_som / price_rate

        # Cost: manual override (вписанная себестоимость) or dynamic from weight
        # (в «прямой сумме» без веса — от расчётного веса, выведенного из суммы).
        if self.cost_is_manual:
            self.cost_som = _money(Decimal(self.cost_som or 0))
        else:
            self.cost_som = _money(cost_weight * self.cost_per_kg_som)

        self.margin_som = self.price_som - self.cost_som

        # Payment defaults: fully paid on the same day unless specified.
        if self.paid_som in (None, ""):
            self.paid_som = self.price_som
        if self.payment_date in (None, ""):
            self.payment_date = self.date

    def save(self, *args, **kwargs):
        self._apply_pricing()
        super().save(*args, **kwargs)


class ClientPrice(models.Model):
    """Индивидуальная цена за 1 кг (сом) для конкретного клиента (по коду).

    По умолчанию цена за кг берётся из Настроек (3$ × курс ≈ 270 сом). Если у
    клиента есть своя цена (напр. 250 или 220 сом/кг) — она подставляется в новой
    продаже Express «по весу» и её можно переопределить вручную."""

    client_code = models.CharField(max_length=120, unique=True, verbose_name="Код клиента")
    price_per_kg_som = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="Цена за 1 кг (сом)"
    )
    note = models.CharField(max_length=255, blank=True, verbose_name="Комментарий")
    created_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="client_prices",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Цена клиента"
        verbose_name_plural = "Цены клиентов"
        ordering = ("client_code",)

    def __str__(self) -> str:
        return f"{self.client_code}: {self.price_per_kg_som} сом/кг"
