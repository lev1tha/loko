from decimal import Decimal, InvalidOperation

from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)

from accounts.permissions import DenyOperatorOrDirector, IsAdmin, SalesAccess, WarehouseAccess
from finance.models import Account, AppSettings, Branch
from .models import ClientPrice, Sale, WarehouseOrder
from .serializers import (
    ClientPriceSerializer,
    OperatorSaleSerializer,
    SaleSerializer,
    WarehouseOrderSerializer,
    WarehouseStatusSerializer,
)

ZERO = Decimal("0.00")


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("from", OpenApiTypes.DATE, description="Начало периода"),
            OpenApiParameter("to", OpenApiTypes.DATE, description="Конец периода"),
            OpenApiParameter("payment", OpenApiTypes.STR, enum=["all", "cash", "noncash"], description="Вид оплаты"),
            OpenApiParameter("search", OpenApiTypes.STR, description="Поиск по коду клиента"),
            OpenApiParameter("branch", OpenApiTypes.INT, description="Филиал Express (id)"),
        ]
    )
)
class SaleViewSet(viewsets.ModelViewSet):
    serializer_class = SaleSerializer
    # Managers/admins: full access. Operators («Сотрудник»): create + quote +
    # the minimal account picker only (enforced per-action by SalesAccess).
    permission_classes = [SalesAccess]

    def get_permissions(self):
        # Экспорт всей таблицы продаж (с финансовыми полями) — только администратор.
        if self.action == "export":
            return [IsAdmin()]
        return [SalesAccess()]

    def get_serializer_class(self):
        # Операторам — узкий сериализатор без финансовых полей: ни себестоимость/
        # маржа/ставки в ответе на create, ни возможность задать их через тело.
        if getattr(self.request.user, "is_operator", False):
            return OperatorSaleSerializer
        return SaleSerializer

    def get_queryset(self):
        qs = Sale.objects.select_related("account").all()
        params = self.request.query_params
        date_from = params.get("from")
        date_to = params.get("to")
        payment = params.get("payment")
        search = params.get("search")
        branch = params.get("branch")
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        if payment == "cash":
            qs = qs.filter(account__kind="CASH")
        elif payment == "noncash":
            qs = qs.filter(account__kind="BANK")
        if search:
            qs = qs.filter(client_code__icontains=search)
        if branch:
            qs = qs.filter(branch=branch)
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        # Филиал: у оператора («Сотрудник») — строго ЕГО закреплённый филиал (подмена
        # невозможна, дефолтного фолбэка нет). Продажа записывается в тот филиал, к
        # которому привязан сотрудник; филиал не назначен → это ошибка настройки, и
        # мы блокируем с понятным сообщением, а не пишем молча «по умолчанию».
        # У менеджера/админа — выбранный в форме, иначе филиал по умолчанию.
        if getattr(user, "is_operator", False):
            branch = user.branch
            if branch is None:
                raise serializers.ValidationError(
                    {"branch": "Вам не назначен филиал. Обратитесь к администратору — "
                               "он привяжет вас к филиалу в разделе «Пользователи»."}
                )
        else:
            branch = serializer.validated_data.get("branch") or Branch.resolve_default()
        sale = serializer.save(created_by=user, branch=branch)
        # «Новая продажа» оператора = заявка на склад: автоматически создаём заявку
        # на сборку из кода клиента — складовщик сразу её видит.
        if getattr(user, "is_operator", False) and sale.client_code:
            wo = WarehouseOrder.objects.create(
                branch=branch,
                created_by=user,
                client_codes=[sale.client_code.strip()],
                status=WarehouseOrder.Status.NEW,
            )
            wo.sales.add(sale)

    @extend_schema(responses=OpenApiTypes.OBJECT)
    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Aggregated totals over the current filter (for dashboard cards)."""
        qs = self.get_queryset()
        agg = qs.aggregate(
            count=Count("id"),
            revenue=Sum("price_som"),
            paid=Sum("paid_som"),
            cost=Sum("cost_som"),
            margin=Sum("margin_som"),
            weight=Sum("weight_kg"),
        )
        revenue = agg["revenue"] or ZERO
        paid = agg["paid"] or ZERO
        return Response(
            {
                "count": agg["count"] or 0,
                "revenue": revenue,                 # начисление
                "paid": paid,                       # оплата
                "receivable": revenue - paid,       # дебиторка
                "cost": agg["cost"] or ZERO,
                "margin": agg["margin"] or ZERO,
                "weight": agg["weight"] or ZERO,
            }
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("from", OpenApiTypes.DATE, description="Начало периода"),
            OpenApiParameter("to", OpenApiTypes.DATE, description="Конец периода"),
            OpenApiParameter("payment", OpenApiTypes.STR, enum=["all", "cash", "noncash"], description="Вид оплаты"),
            OpenApiParameter("search", OpenApiTypes.STR, description="Поиск по коду клиента"),
            OpenApiParameter("branch", OpenApiTypes.INT, description="Филиал Express (id)"),
        ],
        responses=OpenApiTypes.BINARY,
    )
    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        """Выгрузка продаж Express (по текущим фильтрам) в Excel — только администратор.

        Полная таблица с финансами: себестоимость, маржа, дебиторка + итоговая строка.
        Фильтры (даты/оплата/поиск/филиал) — те же, что и в списке (``get_queryset``).
        """
        qs = self.get_queryset().select_related("account", "branch").order_by("-date", "-id")
        return self._export_xlsx(qs)

    @staticmethod
    def _export_xlsx(qs):
        """Полная выгрузка продаж Express в .xlsx (openpyxl) с итоговой строкой."""
        from django.http import HttpResponse
        from openpyxl import Workbook
        from openpyxl.styles import Font

        wb = Workbook()
        ws = wb.active
        ws.title = "Продажи Express"
        headers = [
            "Дата", "Код клиента", "Режим", "Вес, кг", "Кол-во", "Счёт", "Филиал",
            "Начислено, сом", "Оплачено, сом", "Дебиторка, сом",
            "Себестоимость, сом", "Маржа, сом", "Дата оплаты",
        ]
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)

        t_price = t_paid = t_recv = t_cost = t_margin = ZERO
        for s in qs:
            price = s.price_som or ZERO
            paid = s.paid_som or ZERO
            recv = s.receivable_som
            cost = s.cost_som or ZERO
            margin = s.margin_som or ZERO
            t_price += price
            t_paid += paid
            t_recv += recv
            t_cost += cost
            t_margin += margin
            ws.append([
                s.date.strftime("%d.%m.%Y") if s.date else "",
                s.client_code,
                s.get_amount_mode_display(),
                float(s.weight_kg) if s.weight_kg is not None else None,
                s.places,
                s.account.name if s.account_id else "",
                s.branch.name if s.branch_id else "—",
                float(price), float(paid), float(recv), float(cost), float(margin),
                s.payment_date.strftime("%d.%m.%Y") if s.payment_date else "",
            ])

        ws.append([
            "ИТОГО", "", "", "", "", "", "",
            float(t_price), float(t_paid), float(t_recv), float(t_cost), float(t_margin), "",
        ])
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)

        for i, width in enumerate((12, 16, 16, 10, 8, 16, 26, 15, 14, 14, 16, 14, 12)):
            ws.column_dimensions[ws.cell(row=1, column=i + 1).column_letter].width = width

        resp = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        resp["Content-Disposition"] = 'attachment; filename="sales-express.xlsx"'
        wb.save(resp)
        return resp

    @extend_schema(
        parameters=[
            OpenApiParameter("from", OpenApiTypes.DATE, description="Начало периода"),
            OpenApiParameter("to", OpenApiTypes.DATE, description="Конец периода"),
        ],
        responses=OpenApiTypes.OBJECT,
    )
    @action(detail=False, methods=["get"], url_path="weight-summary")
    def weight_summary(self, request):
        """Общий вес (фактический + расчётный) за отдельный период.

        Виджет с собственным фильтром дат — независим от основного фильтра списка
        (``from``/``to`` здесь свои). Суммирует явно введённый вес, а для продаж
        «прямой суммой» без веса — расчётный вес из суммы, ровно как значения «≈»
        в таблице (см. ``Sale.est_weight_kg``): цена ÷ (цена_за_кг_$ × курс_$).
        """
        qs = Sale.objects.all()
        date_from = request.query_params.get("from")
        date_to = request.query_params.get("to")
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        # est_weight_kg — свойство модели (не поле БД), поэтому агрегируем в Python
        # по тем же полям, что и в таблице → карточка сходится с колонкой «Вес».
        qs = qs.only("weight_kg", "price_som", "price_per_kg_usd", "usd_rate_som")
        actual = ZERO  # из явно введённого веса
        est = ZERO     # расчётный (из суммы) — продажи «прямой суммой» без веса
        count = 0
        for sale in qs.iterator():
            count += 1
            w = sale.est_weight_kg
            if w is None:
                continue
            if sale.weight_kg is not None:
                actual += w
            else:
                est += w
        return Response(
            {
                "count": count,
                "weight": actual + est,   # общий вес: факт + расчётный
                "weight_actual": actual,
                "weight_est": est,
            }
        )

    @extend_schema(
        request=inline_serializer(
            "SaleQuoteRequest",
            {
                "weight_kg": serializers.DecimalField(max_digits=10, decimal_places=3),
                "client_code": serializers.CharField(required=False),
            },
        ),
        responses=OpenApiTypes.OBJECT,
    )
    @action(detail=False, methods=["post"], url_path="quote")
    def quote(self, request):
        """Live price/cost/margin preview without persisting a sale.

        Если передан ``client_code`` со спец-ценой — итог считается по цене клиента
        (саму цену в ответе оператору не раскрываем — только итоговую стоимость)."""
        cfg = AppSettings.load()
        try:
            weight = Decimal(str(request.data.get("weight_kg", "0")))
        except (TypeError, ValueError, InvalidOperation):
            weight = ZERO
        # Отсекаем не-числа, отрицательные и абсурдно большие значения (иначе
        # quantize переполняется → 500). Верх — ёмкость поля weight_kg.
        if not weight.is_finite() or weight < 0 or weight > Decimal("9999999.999"):
            weight = ZERO
        # Спец-цена клиента (если есть) — иначе цена по умолчанию из Настроек.
        code = (request.data.get("client_code") or "").strip()
        unit = (
            ClientPrice.objects.filter(client_code=code).values_list("price_per_kg_som", flat=True).first()
            if code else None
        )
        if unit is not None:
            price = (weight * unit).quantize(ZERO)
        else:
            price = (weight * cfg.price_per_kg_usd * cfg.usd_rate_som).quantize(ZERO)
        cost = (weight * cfg.base_cost_per_kg_som).quantize(ZERO)
        # Операторам («Сотрудник») отдаём ТОЛЬКО общую стоимость — без себестоимости,
        # маржи и ставок (даже на уровне API, чтобы их не было видно в devtools).
        if getattr(request.user, "is_operator", False):
            return Response({"weight_kg": weight, "price_som": price})
        return Response(
            {
                "weight_kg": weight,
                "price_per_kg_usd": cfg.price_per_kg_usd,
                "usd_rate_som": cfg.usd_rate_som,
                "cost_per_kg_som": cfg.base_cost_per_kg_som,
                "price_som": price,
                "cost_som": cost,
                "margin_som": price - cost,
            }
        )

    @extend_schema(responses=OpenApiTypes.OBJECT)
    @action(detail=False, methods=["get"], url_path="accounts")
    def express_accounts(self, request):
        """Minimal Express-account picker for the sale form.

        Returns only id/name/kind (NO balances) so the «Сотрудник» role can
        choose where a sale is credited without touching the finance-laden
        /accounts/ endpoint. Sales may only land on Express accounts in сом.
        """
        qs = Account.objects.filter(
            module="EXPRESS", currency="KGS", is_active=True
        ).order_by("name")
        return Response([{"id": a.id, "name": a.name, "kind": a.kind} for a in qs])

    @extend_schema(responses=OpenApiTypes.OBJECT)
    @action(detail=False, methods=["get"], url_path="branches")
    def branches(self, request):
        """Минимальный пикер филиалов Express для формы продажи (id/name активных).

        Доступен и роли «Сотрудник»: его выбор всё равно жёстко фиксируется его
        филиалом на сервере (perform_create). Балансов/финансов не раскрывает.
        """
        from finance.models import Branch
        qs = Branch.objects.filter(is_active=True).order_by("name")
        return Response([{"id": b.id, "name": b.name} for b in qs])

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "export", OpenApiTypes.STR, enum=["xlsx"],
                description="Формат выгрузки: xlsx — файл Excel; иначе JSON",
            )
        ],
        responses=OpenApiTypes.OBJECT,
    )
    @action(detail=False, methods=["get"], url_path="mine")
    def mine(self, request):
        """Свои продажи сотрудника за ТЕКУЩИЙ месяц (новые сверху).

        Возвращает продажи, созданные этим пользователем (``created_by``), с начала
        текущего календарного месяца (по локальному времени). ``?export=xlsx``
        отдаёт файл Excel. Узкий OperatorSaleSerializer не раскрывает
        себестоимость/маржу (как и при создании).
        """
        now_local = timezone.localtime(timezone.now())
        month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        qs = (
            Sale.objects.filter(created_by=request.user, created_at__gte=month_start)
            .select_related("account")
            .order_by("-created_at")
        )
        if request.query_params.get("export") == "xlsx":
            return self._mine_xlsx(qs)
        total = qs.aggregate(s=Sum("price_som"))["s"] or ZERO
        data = self.get_serializer(qs, many=True).data
        return Response({"count": qs.count(), "total_som": total, "results": data})

    @staticmethod
    def _mine_xlsx(qs):
        """Выгрузка «моих продаж за месяц» в .xlsx (openpyxl)."""
        from django.http import HttpResponse
        from openpyxl import Workbook
        from openpyxl.styles import Font

        wb = Workbook()
        ws = wb.active
        ws.title = "Мои продажи"
        ws.append(["Дата", "Время", "Код клиента", "Режим", "Вес, кг", "Кол-во", "Сумма, сом", "Счёт"])
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for s in qs:
            dt = s.created_at
            if timezone.is_aware(dt):
                dt = timezone.localtime(dt)
            ws.append([
                dt.strftime("%d.%m.%Y"),
                dt.strftime("%H:%M"),
                s.client_code,
                s.get_amount_mode_display(),
                float(s.weight_kg) if s.weight_kg is not None else None,
                s.places,
                float(s.price_som or 0),
                s.account.name,
            ])
        for col, width in zip("ABCDEFGH", (12, 8, 16, 16, 10, 8, 12, 18)):
            ws.column_dimensions[col].width = width

        resp = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        resp["Content-Disposition"] = 'attachment; filename="my-sales.xlsx"'
        wb.save(resp)
        return resp


@extend_schema_view(
    list=extend_schema(
        parameters=[OpenApiParameter("client_code", OpenApiTypes.STR, description="Точный код клиента (для подстановки цены)")]
    )
)
class ClientPriceViewSet(viewsets.ModelViewSet):
    """Индивидуальные цены за кг по клиентам (Express).

    Менеджер/админ управляют; операторы и директора — без доступа. Создание —
    «upsert»: если для кода клиента цена уже есть, обновляем её (не плодим дубли)."""

    serializer_class = ClientPriceSerializer
    permission_classes = [DenyOperatorOrDirector]

    def get_queryset(self):
        qs = ClientPrice.objects.all()
        code = self.request.query_params.get("client_code")
        if code:
            qs = qs.filter(client_code=code.strip())
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        # Upsert по коду клиента: повторное сохранение обновляет цену, а не падает
        # на unique-ограничении.
        code = (request.data.get("client_code") or "").strip()
        existing = ClientPrice.objects.filter(client_code=code).first()
        if existing:
            serializer = self.get_serializer(existing, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
        return super().create(request, *args, **kwargs)


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("status", OpenApiTypes.STR, enum=[s.value for s in WarehouseOrder.Status], description="Фильтр по статусу"),
            OpenApiParameter("branch", OpenApiTypes.INT, description="Филиал (менеджер/админ)"),
            OpenApiParameter("search", OpenApiTypes.STR, description="Поиск по коду клиента"),
            OpenApiParameter("active", OpenApiTypes.STR, description="1 = только активные (не Выдано/Отменена)"),
        ]
    )
)
class WarehouseOrderViewSet(viewsets.ModelViewSet):
    """Заявки на сборку (склад Loko Express).

    * Складовщик/оператор — видят только СВОЙ филиал.
    * Менеджер/админ — все заявки (фильтры status/branch/search).
    Статус меняется через action ``status`` (валидация перехода + роли).
    """

    serializer_class = WarehouseOrderSerializer
    permission_classes = [WarehouseAccess]

    def get_queryset(self):
        qs = WarehouseOrder.objects.select_related("branch", "created_by", "assigned_to")
        user = self.request.user
        params = self.request.query_params
        # Склад и оператор — только заявки своего филиала.
        if getattr(user, "is_warehouse", False) or getattr(user, "is_operator", False):
            qs = qs.filter(branch=user.branch) if user.branch_id else qs.none()
        else:
            branch = params.get("branch")
            if branch:
                qs = qs.filter(branch=branch)
        status = params.get("status")
        if status:
            qs = qs.filter(status=status)
        if params.get("active") in ("1", "true", "True"):
            qs = qs.exclude(status__in=[WarehouseOrder.Status.ISSUED, WarehouseOrder.Status.CANCELLED])
        search = (params.get("search") or "").strip().lower()
        if search:
            ids = [o.id for o in qs if any(search in str(c).lower() for c in (o.client_codes or []))]
            qs = qs.filter(id__in=ids)
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        # Филиал заявки: у оператора — его филиал; у менеджера/админа — выбранный,
        # иначе филиал по умолчанию (как у продаж).
        if getattr(user, "is_operator", False) or getattr(user, "is_warehouse", False):
            branch = user.branch or Branch.resolve_default()
        else:
            branch = serializer.validated_data.get("branch") or user.branch or Branch.resolve_default()
        serializer.save(created_by=user, branch=branch, status=WarehouseOrder.Status.NEW)

    @extend_schema(request=WarehouseStatusSerializer, responses=WarehouseOrderSerializer)
    @action(detail=True, methods=["patch", "post"], url_path="status")
    def status(self, request, pk=None):
        """Смена статуса заявки по карте TRANSITIONS.

        Складовщик ведёт весь цикл: в поиск → готова → выдано (либо отмена с
        обязательной причиной). «Взять в работу» фиксирует складовщика (assigned_to)."""
        order = self.get_object()
        ser = WarehouseStatusSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        new_status = ser.validated_data["status"]
        comment = (ser.validated_data.get("comment") or "").strip()
        user = request.user
        labels = dict(WarehouseOrder.Status.choices)

        if new_status != order.status and not order.can_transition_to(new_status):
            raise serializers.ValidationError(
                {"status": f"Недопустимый переход: {order.get_status_display()} → {labels.get(new_status, new_status)}."}
            )
        if new_status == WarehouseOrder.Status.CANCELLED and not comment:
            raise serializers.ValidationError({"comment": "Укажите причину отмены."})

        order.status = new_status
        if comment:
            order.comment = comment
        if new_status == WarehouseOrder.Status.IN_PROGRESS and order.assigned_to_id is None:
            order.assigned_to = user
        order.save()
        return Response(WarehouseOrderSerializer(order).data)
