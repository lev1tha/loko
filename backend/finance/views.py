import io
from decimal import Decimal, InvalidOperation

import segno
from django.conf import settings
from django.db.models import ProtectedError
from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema

from accounts.permissions import DenyOperator, DenyOperatorOrDirector, IsAdmin
from .bonuses import build_bonuses
from .models import Account, AppSettings, Branch, EmployeeBonus, Expense, OtherIncome, Transfer
from .reports import (
    accounts_snapshot,
    breakdown,
    build_cashflow,
    build_monthly,
    build_pnl,
    business_orders,
    debts_summary,
    journal,
)
from .serializers import (
    AccountSerializer,
    AppSettingsSerializer,
    BranchSerializer,
    EmployeeBonusSerializer,
    ExpenseSerializer,
    OtherIncomeSerializer,
    TransferSerializer,
)


def _period_params(request):
    date_from = request.query_params.get("from") or None
    date_to = request.query_params.get("to") or None
    payment = request.query_params.get("payment", "all")
    if payment not in ("all", "cash", "noncash"):
        payment = "all"
    return date_from, date_to, payment


def _scoped_module(request):
    """Направление отчёта. Для директора жёстко фиксируется его направлением
    (защита на сервере — клиент не может попросить чужой раздел)."""
    user = request.user
    if getattr(user, "is_director", False):
        # Директор без направления не видит ничего (служебный «нет данных»).
        return user.module or "__none__"
    return request.query_params.get("module") or None


def _scoped_branch(request):
    """Филиал Express (тег операций). Возвращает id или None. Игнорируется, когда
    направление — Business или у директора нет направления (филиал — только Express
    и не должен обходить scope пользователя)."""
    module = _scoped_module(request)
    if module in ("BUSINESS", "__none__"):
        return None
    raw = request.query_params.get("branch")
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# Reusable OpenAPI query parameters shared by the report endpoints.
PERIOD_PARAMS = [
    OpenApiParameter("from", OpenApiTypes.DATE, description="Начало периода (YYYY-MM-DD)"),
    OpenApiParameter("to", OpenApiTypes.DATE, description="Конец периода (YYYY-MM-DD)"),
    OpenApiParameter("payment", OpenApiTypes.STR, enum=["all", "cash", "noncash"], description="Вид оплаты"),
    OpenApiParameter("module", OpenApiTypes.STR, enum=["EXPRESS", "BUSINESS"], description="Направление (пусто = всё)"),
    OpenApiParameter("branch", OpenApiTypes.INT, description="Филиал Express (id); пусто = все филиалы"),
]


class AppSettingsView(APIView):
    """Singleton settings — readable by all, editable by admins only."""

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH"):
            return [IsAdmin()]
        # Read is open to managers/admins but blocked for the operator and
        # director roles (settings expose tax rates / cost price).
        return [DenyOperatorOrDirector()]

    @extend_schema(responses=AppSettingsSerializer)
    def get(self, request):
        return Response(AppSettingsSerializer(AppSettings.load()).data)

    @extend_schema(request=AppSettingsSerializer, responses=AppSettingsSerializer)
    def put(self, request):
        return self._update(request)

    @extend_schema(request=AppSettingsSerializer, responses=AppSettingsSerializer)
    def patch(self, request):
        return self._update(request)

    def _update(self, request):
        instance = AppSettings.load()
        serializer = AppSettingsSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class AccountViewSet(viewsets.ModelViewSet):
    serializer_class = AccountSerializer

    def get_queryset(self):
        qs = Account.objects.all()
        module = self.request.query_params.get("module")
        if module:
            qs = qs.filter(module=module)
        return qs

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            # Account listings carry balances → never exposed to operators/directors.
            return [DenyOperatorOrDirector()]
        return [IsAdmin()]

    def destroy(self, request, *args, **kwargs):
        # Счёт с операциями защищён FK (PROTECT) — отдаём понятную 409, не 500.
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {"detail": "Нельзя удалить счёт с операциями. Перенесите/удалите операции "
                           "или отметьте счёт неактивным."},
                status=409,
            )


class BranchViewSet(viewsets.ModelViewSet):
    """Филиалы Loko Express. Чтение — менеджер/админ (для фильтра отчётов и формы
    продажи); запись — только админ. Оператор получает пикер через /sales/branches/."""

    serializer_class = BranchSerializer

    def get_queryset(self):
        qs = Branch.objects.all()
        if self.request.query_params.get("active") in ("1", "true", "True"):
            qs = qs.filter(is_active=True)
        return qs

    def get_permissions(self):
        # Чтение (в т.ч. QR филиала) — менеджер/админ; запись — только админ.
        if self.action in ("list", "retrieve", "qr"):
            return [DenyOperatorOrDirector()]
        return [IsAdmin()]

    def destroy(self, request, *args, **kwargs):
        # Филиал с операциями защищён FK (PROTECT) — 409, не 500 (как у счёта).
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {"detail": "Нельзя удалить филиал с привязанными операциями. "
                           "Отметьте его неактивным."},
                status=409,
            )

    @extend_schema(
        parameters=[OpenApiParameter(
            "fmt", OpenApiTypes.STR, enum=["svg", "png"],
            description="Формат: svg (по умолчанию, вектор для печати) или png",
        )],
        responses=OpenApiTypes.BINARY,
    )
    @action(detail=True, methods=["get"])
    def qr(self, request, pk=None):
        """QR-код филиала: ведёт на публичную клиентскую страницу этого филиала
        (``PUBLIC_SITE_URL/track?b=<id>``). Клиент сканирует его на баннере и,
        не заходя в систему, сдаёт коды на склад. ECC уровня H — устойчив к
        печати/затиранию. Возвращает SVG (по умолчанию) или PNG.

        Параметр называется ``fmt``, а НЕ ``format``: последний перехватывает DRF
        для выбора рендерера (?format=png → 404)."""
        branch = self.get_object()
        url = f"{settings.PUBLIC_SITE_URL.rstrip('/')}/track?b={branch.id}"
        qr = segno.make(url, error="h")
        fmt = (request.query_params.get("fmt") or "svg").lower()
        buf = io.BytesIO()
        if fmt == "png":
            qr.save(buf, kind="png", scale=12, border=3, dark="#111111", light="#ffffff")
            content_type, ext = "image/png", "png"
        else:
            qr.save(buf, kind="svg", scale=12, border=3, dark="#111111", light="#ffffff")
            content_type, ext = "image/svg+xml", "svg"
        resp = HttpResponse(buf.getvalue(), content_type=content_type)
        resp["Content-Disposition"] = f'inline; filename="loko-qr-branch-{branch.id}.{ext}"'
        return resp


class ExpenseViewSet(viewsets.ModelViewSet):
    serializer_class = ExpenseSerializer
    permission_classes = [DenyOperatorOrDirector]

    def get_queryset(self):
        qs = Expense.objects.select_related("account").all()
        date_from, date_to, _ = _period_params(self.request)
        category = self.request.query_params.get("category")
        account = self.request.query_params.get("account")
        module = self.request.query_params.get("module")
        branch = self.request.query_params.get("branch")
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        if category:
            qs = qs.filter(category=category)
        if account:
            qs = qs.filter(account_id=account)
        if module:
            qs = qs.filter(account__module=module)
        if branch:
            qs = qs.filter(branch=branch)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class OtherIncomeViewSet(viewsets.ModelViewSet):
    serializer_class = OtherIncomeSerializer
    permission_classes = [DenyOperatorOrDirector]

    def get_queryset(self):
        qs = OtherIncome.objects.select_related("account").all()
        date_from, date_to, _ = _period_params(self.request)
        module = self.request.query_params.get("module")
        account = self.request.query_params.get("account")
        branch = self.request.query_params.get("branch")
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        if module:
            qs = qs.filter(account__module=module)
        if account:
            qs = qs.filter(account_id=account)
        if branch:
            qs = qs.filter(branch=branch)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class TransferViewSet(viewsets.ModelViewSet):
    serializer_class = TransferSerializer
    permission_classes = [DenyOperatorOrDirector]

    def get_queryset(self):
        qs = Transfer.objects.select_related("from_account", "to_account").all()
        date_from, date_to, _ = _period_params(self.request)
        module = self.request.query_params.get("module")
        branch = self.request.query_params.get("branch")
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        if module:
            qs = qs.filter(from_account__module=module)
        if branch:
            qs = qs.filter(branch=branch)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


@extend_schema(
    parameters=PERIOD_PARAMS
    + [OpenApiParameter("tax_rate", OpenApiTypes.NUMBER, description="Ставка налога %, пусто = из настроек")],
    responses=OpenApiTypes.OBJECT,
    tags=["reports"],
)
@api_view(["GET"])
@permission_classes([DenyOperator])
def pnl_report(request):
    date_from, date_to, payment = _period_params(request)
    module = _scoped_module(request)
    branch = _scoped_branch(request)
    # Санитизируем ручную ставку налога: только неотрицательное число, иначе игнор.
    tax_rate = request.query_params.get("tax_rate")
    if tax_rate in ("", None):
        tax_rate = None
    else:
        try:
            if Decimal(str(tax_rate)) < 0:
                tax_rate = None
        except (InvalidOperation, ValueError, TypeError):
            tax_rate = None
    return Response(build_pnl(date_from, date_to, payment, tax_rate=tax_rate, module=module, branch=branch))


@extend_schema(
    parameters=PERIOD_PARAMS
    + [OpenApiParameter("opening", OpenApiTypes.NUMBER, description="Остаток на начало вручную (перенос с прошлого месяца)")],
    responses=OpenApiTypes.OBJECT,
    tags=["reports"],
)
@api_view(["GET"])
@permission_classes([DenyOperator])
def cashflow_report(request):
    date_from, date_to, payment = _period_params(request)
    module = _scoped_module(request)
    branch = _scoped_branch(request)
    opening_override = None
    raw = request.query_params.get("opening")
    if raw not in (None, ""):
        try:
            opening_override = Decimal(str(raw))
        except (InvalidOperation, ValueError, TypeError):
            opening_override = None
    return Response(build_cashflow(date_from, date_to, payment, module=module, opening_override=opening_override, branch=branch))


@extend_schema(
    parameters=PERIOD_PARAMS
    + [
        OpenApiParameter("module", OpenApiTypes.STR, enum=["EXPRESS", "BUSINESS"], description="Направление"),
        OpenApiParameter("report", OpenApiTypes.STR, enum=["pnl", "cashflow"], description="Какой отчёт разбить по месяцам"),
    ],
    responses=OpenApiTypes.OBJECT,
    tags=["reports"],
)
@api_view(["GET"])
@permission_classes([DenyOperator])
def monthly_report(request):
    date_from, date_to, _ = _period_params(request)
    module = _scoped_module(request)
    branch = _scoped_branch(request)
    report = request.query_params.get("report", "pnl")
    if report not in ("pnl", "cashflow"):
        report = "pnl"
    return Response(build_monthly(date_from, date_to, module=module, report=report, branch=branch))


@extend_schema(
    parameters=[OpenApiParameter("module", OpenApiTypes.STR, enum=["EXPRESS", "BUSINESS"], description="Направление")],
    responses=OpenApiTypes.OBJECT,
    tags=["reports"],
)
@api_view(["GET"])
@permission_classes([DenyOperatorOrDirector])
def balances(request):
    module = request.query_params.get("module")
    return Response(accounts_snapshot(module=module))


@extend_schema(responses=OpenApiTypes.OBJECT, tags=["reports"])
@api_view(["GET"])
@permission_classes([DenyOperatorOrDirector])
def debts_report(request):
    return Response(debts_summary())


@extend_schema(parameters=PERIOD_PARAMS, responses=OpenApiTypes.OBJECT, tags=["reports"])
@api_view(["GET"])
@permission_classes([DenyOperatorOrDirector])
def business_orders_report(request):
    date_from, date_to, _ = _period_params(request)
    return Response(business_orders(date_from, date_to))


@extend_schema(
    parameters=PERIOD_PARAMS
    + [
        OpenApiParameter("module", OpenApiTypes.STR, enum=["EXPRESS", "BUSINESS"], description="Направление"),
        OpenApiParameter("effect", OpenApiTypes.STR, description="Фильтр строк по эффекту (Выручка/Опер. расход/…)"),
        OpenApiParameter("limit", OpenApiTypes.INT, description="Размер страницы (по умолч. 500, макс 2000)"),
        OpenApiParameter("offset", OpenApiTypes.INT, description="Смещение страницы"),
    ],
    responses=OpenApiTypes.OBJECT,
    tags=["reports"],
)
@api_view(["GET"])
@permission_classes([DenyOperatorOrDirector])
def journal_report(request):
    date_from, date_to, _ = _period_params(request)
    module = request.query_params.get("module") or None
    branch = _scoped_branch(request)
    effect = request.query_params.get("effect") or None

    def _int(name, default):
        try:
            return int(request.query_params.get(name, default))
        except (TypeError, ValueError):
            return default

    return Response(journal(
        date_from, date_to, module=module, effect_filter=effect,
        limit=_int("limit", 500), offset=_int("offset", 0), branch=branch,
    ))


@extend_schema(
    parameters=PERIOD_PARAMS
    + [
        OpenApiParameter(
            "line",
            OpenApiTypes.STR,
            description="Строка отчёта: revenue | express_revenue | deposit_revenue | cogs | opex | "
            "opex_<СТАТЬЯ> | other | supplier | owner | inflow | outflow",
        ),
        OpenApiParameter("basis", OpenApiTypes.STR, enum=["accrual", "cash"], description="accrual = ОПиУ, cash = ОДДС"),
    ],
    responses=OpenApiTypes.OBJECT,
    tags=["reports"],
)
@api_view(["GET"])
@permission_classes([DenyOperator])
def breakdown_report(request):
    date_from, date_to, payment = _period_params(request)
    line = request.query_params.get("line", "revenue")
    module = _scoped_module(request)
    branch = _scoped_branch(request)
    basis = request.query_params.get("basis", "accrual")
    return Response(breakdown(line, date_from, date_to, payment, module, basis, branch=branch))


@extend_schema(
    parameters=[OpenApiParameter("period", OpenApiTypes.STR, description="Месяц в формате YYYY-MM (по умолчанию текущий)")],
    responses=OpenApiTypes.OBJECT,
    tags=["reports"],
)
@api_view(["GET"])
@permission_classes([DenyOperatorOrDirector])
def bonuses_report(request):
    """Месячные бонусы всех сотрудников (KPI-система). Менеджер/админ.

    Оборот и стаж считаются из данных; оклад/дисциплина/проверка/звёзды/отзывы —
    ручные (правятся через PATCH /api/bonuses/<id>/)."""
    import re
    from django.utils import timezone

    period = request.query_params.get("period") or ""
    if not re.match(r"^\d{4}-\d{2}$", period):
        period = timezone.localdate().strftime("%Y-%m")
    return Response({"period": period, "rows": build_bonuses(period)})


class EmployeeBonusViewSet(viewsets.ModelViewSet):
    """Правка «ручных» полей бонуса (оклад/дисциплина/проверка/звёзды/отзывы).

    Список с расчётом — отдельным отчётом ``/api/reports/bonuses/``. Здесь только
    PATCH по id (строки создаются при расчёте). Доступ — менеджер/админ."""

    queryset = EmployeeBonus.objects.all()
    serializer_class = EmployeeBonusSerializer
    permission_classes = [DenyOperatorOrDirector]
    http_method_names = ["patch", "head", "options"]
