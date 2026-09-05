from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings as dj_settings
from django.db import models, transaction
from django.utils import timezone

from finance.models import Account, AppSettings

TWO_PLACES = Decimal("0.01")
THREE_PLACES = Decimal("0.001")


def _money(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


class DeliveryStatus(models.TextChoices):
    """Статус заказа Kargo Osh (``orders.i_status`` 1/2/3)."""

    TRANSIT = "TRANSIT", "В пути"
    ARRIVED = "ARRIVED", "На складе"
    DELIVERED = "DELIVERED", "Отдан"


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
    branch = models.ForeignKey(
        "finance.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sales",
        verbose_name="Филиал",
        help_text="Точка приёма Express (обязательно для новых продаж)",
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
    # --- интеграция Kargo Osh (миграция заказов) -----------------------------
    tracking_number = models.CharField(
        max_length=120, null=True, blank=True, unique=True, verbose_name="Трек-номер (Kargo)",
    )
    shipment_date = models.DateField(null=True, blank=True, verbose_name="Дата отгрузки (Kargo)")
    arrival_date = models.DateField(null=True, blank=True, verbose_name="Дата прибытия на склад (Kargo)")
    # Жизненный цикл заказа Kargo: в пути → на складе → отдан. NULL — продажа,
    # созданная в Loko (склад/оператор): груз уже выдан клиенту.
    delivery_status = models.CharField(
        max_length=10, choices=DeliveryStatus.choices, null=True, blank=True,
        db_index=True, verbose_name="Статус доставки (Kargo)",
    )
    legacy_kargo_id = models.IntegerField(
        null=True, blank=True, unique=True, verbose_name="ID заказа в Kargo Osh",
    )
    # Обратный мост Loko → Kargoosh: продажа, созданная в Loko, отправляется в
    # таблицу orders сайта (клиент видит её в кабинете kargoosh.kg). Для таких
    # строк Loko — главный: импорт из Kargoosh их не перезаписывает.
    kargo_sync_pending = models.BooleanField(
        default=False, db_index=True, verbose_name="Ждёт отправки в Kargoosh",
    )
    kargo_pushed_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Отправлено в Kargoosh",
    )
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


class WarehouseOrder(models.Model):
    """Заявка на сборку (склад Loko Express).

    Оператор/менеджер филиала формирует заявку из 1–5 кодов клиентов; складовщик
    ведёт её по статусам (в поиске → готова), кассир выдаёт после оплаты. Заявка
    привязана к филиалу — складовщик видит только заявки своего филиала.
    """

    class Status(models.TextChoices):
        NEW = "NEW", "Новая"
        IN_PROGRESS = "IN_PROGRESS", "В поиске"
        READY = "READY", "Готова к выдаче"
        NOT_FOUND = "NOT_FOUND", "Не найдено"
        ISSUED = "ISSUED", "Выдано"
        CANCELLED = "CANCELLED", "Отменена"

    # Разрешённые переходы статусов (валидируются в сериализаторе/вьюсете).
    # «Не найдено» — обратимое проблемное состояние (не терминальное, как отмена):
    # товара нет на складе → можно вернуть «В поиск» (нашёлся/приехал) или отменить.
    TRANSITIONS = {
        "NEW": {"IN_PROGRESS", "CANCELLED"},
        "IN_PROGRESS": {"READY", "NOT_FOUND", "CANCELLED", "NEW"},
        "READY": {"ISSUED", "IN_PROGRESS", "NOT_FOUND", "CANCELLED"},
        "NOT_FOUND": {"IN_PROGRESS", "CANCELLED"},
        "ISSUED": set(),
        "CANCELLED": set(),
    }
    # Заявка-«чек» может содержать много мест одного клиента — держим щедрый лимит.
    MAX_CODES = 50

    branch = models.ForeignKey(
        "finance.Branch", on_delete=models.PROTECT, related_name="warehouse_orders",
        verbose_name="Филиал сборки",
    )
    # Клиент заявки (по телефону, если пришла через QR/самообслуживание). У заявок,
    # созданных оператором вручную, может быть пусто.
    client = models.ForeignKey(
        "Client", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="orders", verbose_name="Клиент",
    )
    # Сотрудник, за которым закреплена заявка: он видит её в «Моих продажах» и ему
    # засчитывается продажа. Оператор создаёт заявку сам; заявка клиента (QR) при
    # приёме закрепляется за единственным сотрудником филиала автоматически, а если
    # сотрудников несколько — складовщик выбирает при оприходовании. Пусто — ещё
    # никому не закреплена (заявка от клиента, ``client`` заполнен).
    created_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="warehouse_orders_created",
        verbose_name="Сотрудник (кому засчитывается)",
    )
    assigned_to = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="warehouse_orders_assigned", verbose_name="Складовщик",
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.NEW, verbose_name="Статус",
    )

    class Origin(models.TextChoices):
        OPERATOR = "OPERATOR", "Сотрудник"
        CLIENT = "CLIENT", "Клиент (QR)"
        KARGO = "KARGO", "Kargoosh (ожидаемые посылки)"

    # Откуда заявка: сотрудник создал, клиент сдал коды по QR, либо мост завёл её
    # из заказов сайта «в пути» (ожидаемые посылки складу).
    origin = models.CharField(
        max_length=8, choices=Origin.choices, default=Origin.OPERATOR, verbose_name="Источник",
    )
    # Коды клиентов (1–5). JSONField — работает и на SQLite (dev), и на PostgreSQL.
    client_codes = models.JSONField(default=list, verbose_name="Коды клиентов (1–5)")
    sales = models.ManyToManyField(
        Sale, blank=True, related_name="warehouse_orders", verbose_name="Связанные продажи",
    )
    comment = models.TextField(blank=True, verbose_name="Комментарий / причина отмены")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Заявка на сборку"
        verbose_name_plural = "Заявки на сборку (склад)"
        ordering = ("-created_at", "-id")

    def __str__(self) -> str:
        branch = self.branch.name if self.branch_id else "—"
        return f"Заявка #{self.pk} · {self.get_status_display()} · {branch}"

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in self.TRANSITIONS.get(self.status, set())

    @staticmethod
    def branch_operators(branch):
        """Активные сотрудники («Сотрудник») филиала."""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        if branch is None:
            return User.objects.none()
        return User.objects.filter(role=User.Role.OPERATOR, is_active=True, branch=branch).order_by("first_name", "username")

    @classmethod
    def resolve_operator(cls, branch):
        """Единственный сотрудник филиала — иначе None (нужен явный выбор)."""
        ops = list(cls.branch_operators(branch)[:2])
        return ops[0] if len(ops) == 1 else None

    def assign_operator(self, operator):
        """Закрепить заявку за сотрудником (только если ещё не закреплена)."""
        if self.created_by_id is None and operator is not None:
            self.created_by = operator
            self.save(update_fields=["created_by", "updated_at"])


class WarehouseItem(models.Model):
    """Позиция заявки — ОДИН код клиента внутри WarehouseOrder (двухэтапный учёт).

    Оператор создаёт заявку с кодами — все позиции стартуют в ``IN_SEARCH``, без
    денег (финансовой продажи ещё нет). Складовщик оприходует ПОШТУ́ЧНО:
      • FOUND      — вводит фактический вес → создаётся официальная ``Sale`` по
                     тарифу (вес × цена/кг), и ТОЛЬКО тогда позиция попадает в
                     финансы (ОПиУ/ОДДС/касса);
      • NOT_FOUND  — указывает причину, продажа НЕ создаётся;
      • EVENING    — «вечерний допоиск»: оператор отказался от не найденной позиции
                     (крестик), складовщик перепроверяет её в конце смены.
    Инвариант финансов: продажа существует только у FOUND/DELIVERED — черновики,
    IN_SEARCH и NOT_FOUND в отчёты не попадают (у них нет ``Sale``).
    """

    class Status(models.TextChoices):
        EXPECTED = "EXPECTED", "Ожидается"      # посылка известна из Kargoosh («в пути»), ещё не на складе
        IN_SEARCH = "IN_SEARCH", "В поиске"
        LOCATED = "LOCATED", "Найдено, к оприходованию"   # складовщик нашёл; вес и продажу вносит сотрудник
        FOUND = "FOUND", "Оприходовано"
        NOT_FOUND = "NOT_FOUND", "Не найдено"
        EVENING = "EVENING", "Вечерний допоиск"
        DELIVERED = "DELIVERED", "Выдано"

    # Статусы «до оприходования» — позиция без денег.
    OPEN = {"EXPECTED", "IN_SEARCH", "LOCATED", "NOT_FOUND", "EVENING"}

    # Статусы, для которых существует официальная продажа (учитываются финансами).
    FINANCIAL = {Status.FOUND, Status.DELIVERED}

    order = models.ForeignKey(
        WarehouseOrder, on_delete=models.CASCADE, related_name="items", verbose_name="Заявка",
    )
    client_code = models.CharField(max_length=120, verbose_name="Код клиента")
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.IN_SEARCH, verbose_name="Статус",
    )
    weight_kg = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True, verbose_name="Вес (кг)",
    )
    sale = models.OneToOneField(
        "Sale", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="warehouse_item", verbose_name="Продажа (создаётся при оприходовании)",
    )
    reason = models.CharField(max_length=255, blank=True, verbose_name="Причина (не найдено)")
    # Складовщик, который нашёл посылку («Найдено»); ему засчитываются кг склада.
    found_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="warehouse_items_found", verbose_name="Нашёл (складовщик)",
    )
    # Сотрудник, который взвесил и оприходовал (создал продажу).
    received_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="warehouse_items_received", verbose_name="Оприходовал (сотрудник)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Позиция заявки (склад)"
        verbose_name_plural = "Позиции заявок (склад)"
        ordering = ("id",)

    def __str__(self) -> str:
        return f"{self.client_code} · {self.get_status_display()}"

    def receive(self, weight_kg, account, by_user=None, tracking_number=None):
        """Оприходовать позицию: создать официальную продажу Express по весу и тарифу.

        Тариф — как в режиме «по весу» (``Sale`` считает цену в ``save()``: вес ×
        цена/кг из Настроек либо индивидуальная цена клиента). Продажа
        атрибутируется оператору-создателю заявки; себестоимость/маржа — на продаже.
        ``tracking_number`` — необязательный трек-номер посылки (для кабинета
        клиента на kargoosh.kg; без него мост подставит LOKO-<id>).
        """
        weight = Decimal(str(weight_kg)).quantize(THREE_PLACES, rounding=ROUND_HALF_UP)
        track = (tracking_number or "").strip() or None
        # Атомарно: мост Loko → Kargoosh срабатывает по on_commit и должен видеть
        # продажу уже привязанной к позиции (иначе она уйдёт как «прямая», статус 3).
        with transaction.atomic():
            if self.sale_id:
                # Ожидаемая посылка из Kargoosh: продажа уже есть (заказ «в пути»),
                # ОБНОВЛЯЕМ её, а не создаём вторую — иначе выручка задваивается.
                sale = self.sale
                sale.amount_mode = Sale.AmountMode.WEIGHT
                sale.weight_kg = weight
                sale.account = account
                sale.branch = self.order.branch
                sale.date = timezone.localdate()
                sale.arrival_date = timezone.localdate()
                sale.created_by = self.order.created_by
                if track:
                    sale.tracking_number = track
                sale.price_per_kg_usd = None      # тариф пересчитать по текущим Настройкам
                sale.usd_rate_som = None
                sale.cost_per_kg_som = None
                sale.cost_is_manual = False
                sale.paid_som = Decimal("0")      # в цикле Kargo оплата при выдаче
                sale.payment_date = None
                sale.delivery_status = DeliveryStatus.ARRIVED
                sale.save()
            else:
                sale = Sale.objects.create(
                    client_code=self.client_code,
                    amount_mode=Sale.AmountMode.WEIGHT,
                    weight_kg=weight,
                    account=account,
                    branch=self.order.branch,
                    date=timezone.localdate(),
                    created_by=self.order.created_by,
                    tracking_number=track,
                )
            self.sale = sale
            self.weight_kg = weight
            self.reason = ""
            # Кто нашёл — остаётся складовщик (если нажимал «Найдено»); кто оприходовал — текущий.
            if self.found_by_id is None:
                self.found_by = by_user
            self.received_by = by_user
            self.status = self.Status.FOUND
            self.save()
        return sale

    def locate(self, by_user=None):
        """Складовщик нашёл посылку: без денег, ждёт взвешивания и оприходования сотрудником."""
        self.status = self.Status.LOCATED
        self.reason = ""
        self.found_by = by_user
        self.save(update_fields=["status", "reason", "found_by", "updated_at"])

    def mark_not_found(self, reason, by_user=None):
        """Отметить, что товара нет на складе (без создания продажи)."""
        self.status = self.Status.NOT_FOUND
        self.reason = (reason or "").strip()
        self.found_by = by_user
        self.save(update_fields=["status", "reason", "found_by", "updated_at"])

    def send_to_evening(self):
        """Оператор отказался от не найденной позиции → в вечерний допоиск."""
        self.status = self.Status.EVENING
        self.save(update_fields=["status", "updated_at"])


class Client(models.Model):
    """Клиент карго — узнаём по ТЕЛЕФОНУ (регистрация на QR-странице).

    Хранит имя и телефон; история (заказов, кг, сумма) считается по связанным
    заявкам (``orders``). Телефон канонизируется в цифры — для единственности и
    поиска, чтобы «+996 700 12 34 56» и «996 7001234 56» были одним клиентом.
    """

    phone = models.CharField(max_length=32, unique=True, verbose_name="Телефон (канонический)")
    name = models.CharField(max_length=160, blank=True, verbose_name="Имя")
    # --- поля из Kargo Osh (миграция; для новых Loko-клиентов пустые) ----------
    code = models.CharField(
        max_length=32, unique=True, null=True, blank=True, verbose_name="Код клиента",
    )
    last_name = models.CharField(max_length=120, blank=True, verbose_name="Фамилия")
    email = models.EmailField(max_length=160, unique=True, null=True, blank=True)
    # Хеш пароля. Из Kargo переносится как есть — это PHP-схема
    # ``md5(md5(strrev(pw)) . "test_ort")`` (32 hex), проверка в ``express.kargo``.
    # При первом успешном входе через API хеш прозрачно обновляется до
    # стандартного Django (``make_password``). Логины клиентов не сбрасываются.
    password_hash = models.CharField(
        max_length=128, blank=True, verbose_name="Хеш пароля (из Kargo / Django)",
    )
    pass_code = models.CharField(max_length=100, blank=True, verbose_name="Код восстановления")
    pass_date = models.DateTimeField(null=True, blank=True)
    tg_id = models.CharField(max_length=100, blank=True, verbose_name="Telegram id")
    branch = models.ForeignKey(
        "finance.Branch", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="clients", verbose_name="Регион / филиал",
    )
    discount = models.CharField(
        max_length=16, blank=True, verbose_name="Скидка (из Kargo, как есть)",
    )
    is_enabled = models.BooleanField(default=True, verbose_name="Активен")
    reg_date = models.DateTimeField(null=True, blank=True, verbose_name="Дата регистрации (Kargo)")
    access_date = models.DateTimeField(null=True, blank=True, verbose_name="Последний вход (Kargo)")
    access_ip = models.CharField(max_length=45, blank=True)
    legacy_kargo_id = models.IntegerField(
        null=True, blank=True, unique=True, verbose_name="ID клиента в Kargo Osh",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Клиент"
        verbose_name_plural = "Клиенты"
        ordering = ("-created_at", "-id")

    def __str__(self) -> str:
        return f"{self.name or 'Клиент'} · {self.phone}"

    @staticmethod
    def normalize_phone(raw) -> str:
        """Канонический телефон: только цифры, для киргизских номеров — 9 цифр без
        «996» и без ведущего «0» (как хранит kargoosh.kg). «+996 700 12 34 56»,
        «0700123456» и «700123456» — один и тот же клиент."""
        digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
        if len(digits) == 12 and digits.startswith("996"):
            return digits[3:]
        if len(digits) == 10 and digits.startswith("0"):
            return digits[1:]
        return digits

    def check_password(self, raw_password) -> bool:
        """Проверка пароля клиента (legacy-MD5 из Kargo или хеш Django)."""
        from .kargo import check_client_password
        return check_client_password(self, raw_password)

    def set_password(self, raw_password):
        from django.contrib.auth.hashers import make_password
        self.password_hash = make_password(raw_password)

    @classmethod
    def get_or_register(cls, raw_phone, name=""):
        """Найти клиента по телефону или зарегистрировать. Имя дополняем, не затираем."""
        phone = cls.normalize_phone(raw_phone)
        if not phone:
            return None
        client, _ = cls.objects.get_or_create(phone=phone)
        name = (name or "").strip()
        if name and not client.name:
            client.name = name
            client.save(update_fields=["name", "updated_at"])
        return client


class WarehouseStock(models.Model):
    """Учёт веса на складе филиала (ведёт директор).

    Директор записывает, сколько кг пришло на склад за день (``INTAKE``), а
    расход считается автоматически из продаж Loko этого филиала (вес, который
    сотрудники указали при оприходовании). Остаток = Σ приходов − Σ веса продаж
    с даты первой записи; переносится на следующий день (40 кг + 150 кг = 190 кг).
    ``ADJUST`` — ручная корректировка до фактического остатка (может быть < 0).
    """

    class Kind(models.TextChoices):
        INTAKE = "INTAKE", "Приход на склад"
        ADJUST = "ADJUST", "Корректировка остатка"

    branch = models.ForeignKey(
        "finance.Branch", on_delete=models.PROTECT, related_name="stock_entries", verbose_name="Филиал",
    )
    date = models.DateField(verbose_name="Дата")
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.INTAKE, verbose_name="Тип")
    kg = models.DecimalField(max_digits=10, decimal_places=3, verbose_name="Вес (кг)")
    note = models.CharField(max_length=255, blank=True, verbose_name="Комментарий")
    created_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="stock_entries", verbose_name="Записал",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Приход на склад (кг)"
        verbose_name_plural = "Приходы на склад (кг)"
        ordering = ("-date", "-id")

    def __str__(self) -> str:
        return f"{self.branch} · {self.date} · {self.get_kind_display()} {self.kg} кг"


class KargoSync(models.Model):
    """Журнал синхронизаций с Kargo Osh (``import_kargoosh``).

    Одна строка на запуск: режим, окно, счётчики и итог. Последняя успешная
    запись задаёт нижнюю границу окна следующего инкрементального прогона.
    """

    class Mode(models.TextChoices):
        FULL = "FULL", "Полный импорт"
        INCREMENTAL = "INCREMENTAL", "Инкремент"
        RESCAN = "RESCAN", "Полная сверка (upsert)"

    mode = models.CharField(max_length=12, choices=Mode.choices)
    since = models.DateTimeField(null=True, blank=True, verbose_name="Окно с")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    dry_run = models.BooleanField(default=False)
    stats = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        verbose_name = "Синхронизация Kargo"
        verbose_name_plural = "Синхронизации Kargo"
        ordering = ("-started_at",)

    def __str__(self) -> str:
        return f"{self.get_mode_display()} {self.started_at:%Y-%m-%d %H:%M} {'✓' if self.ok else '✗'}"

    @classmethod
    def last_successful(cls):
        return cls.objects.filter(ok=True, dry_run=False).order_by("-started_at").first()


class EmployeeRating(models.Model):
    """Оценка сотрудника клиентом (звёзды 1–5) — питает бонус «звёзды».

    Одна оценка на пару (сотрудник, клиент); клиент может её обновить. Оценивать
    можно только того, кто реально оприходовал груз клиента (проверка во вьюсете).
    Средняя оценка сотрудника авто-подставляется в столбец «Звёзды» его бонуса.
    """

    employee = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="ratings_received", verbose_name="Сотрудник",
    )
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="ratings_given", verbose_name="Клиент",
    )
    stars = models.PositiveSmallIntegerField(verbose_name="Звёзды (1–5)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Оценка сотрудника"
        verbose_name_plural = "Оценки сотрудников (клиентами)"
        unique_together = ("employee", "client")
        ordering = ("-updated_at",)

    def __str__(self) -> str:
        return f"{self.employee} · {self.stars}★ от {self.client}"
