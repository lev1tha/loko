from decimal import Decimal, InvalidOperation

from django.db.models import ProtectedError
from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema

from accounts.permissions import DenyOperator, IsAdmin
from .models import Account, AppSettings, Expense, Transfer
from .reports import (
    accounts_snapshot,
    breakdown,
    build_cashflow,
    build_pnl,
    business_orders,
    debts_summary,
    journal,
)
from .serializers import (
    AccountSerializer,
    AppSettingsSerializer,
    ExpenseSerializer,
    TransferSerializer,
)


def _period_params(request):
    date_from = request.query_params.get("from") or None
    date_to = request.query_params.get("to") or None
    payment = request.query_params.get("payment", "all")
    if payment not in ("all", "cash", "noncash"):
        payment = "all"
    return date_from, date_to, payment


# Reusable OpenAPI query parameters shared by the report endpoints.
PERIOD_PARAMS = [
    OpenApiParameter("from", OpenApiTypes.DATE, description="Начало периода (YYYY-MM-DD)"),
    OpenApiParameter("to", OpenApiTypes.DATE, description="Конец периода (YYYY-MM-DD)"),
    OpenApiParameter("payment", OpenApiTypes.STR, enum=["all", "cash", "noncash"], description="Вид оплаты"),
    OpenApiParameter("module", OpenApiTypes.STR, enum=["EXPRESS", "BUSINESS"], description="Направление (пусто = всё)"),
]


class AppSettingsView(APIView):
    """Singleton settings — readable by all, editable by admins only."""

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH"):
            return [IsAdmin()]
        # Read is open to managers/admins but blocked for the operator role
        # (settings expose tax rates / cost price — financial parameters).
        return [DenyOperator()]

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
            # Account listings carry balances → never exposed to operators.
            return [DenyOperator()]
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


class ExpenseViewSet(viewsets.ModelViewSet):
    serializer_class = ExpenseSerializer
    permission_classes = [DenyOperator]

    def get_queryset(self):
        qs = Expense.objects.select_related("account").all()
        date_from, date_to, _ = _period_params(self.request)
        category = self.request.query_params.get("category")
        account = self.request.query_params.get("account")
        module = self.request.query_params.get("module")
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
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class TransferViewSet(viewsets.ModelViewSet):
    serializer_class = TransferSerializer
    permission_classes = [DenyOperator]

    def get_queryset(self):
        qs = Transfer.objects.select_related("from_account", "to_account").all()
        date_from, date_to, _ = _period_params(self.request)
        module = self.request.query_params.get("module")
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        if module:
            qs = qs.filter(from_account__module=module)
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
    module = request.query_params.get("module") or None
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
    return Response(build_pnl(date_from, date_to, payment, tax_rate=tax_rate, module=module))


@extend_schema(parameters=PERIOD_PARAMS, responses=OpenApiTypes.OBJECT, tags=["reports"])
@api_view(["GET"])
@permission_classes([DenyOperator])
def cashflow_report(request):
    date_from, date_to, payment = _period_params(request)
    module = request.query_params.get("module") or None
    return Response(build_cashflow(date_from, date_to, payment, module=module))


@extend_schema(
    parameters=[OpenApiParameter("module", OpenApiTypes.STR, enum=["EXPRESS", "BUSINESS"], description="Направление")],
    responses=OpenApiTypes.OBJECT,
    tags=["reports"],
)
@api_view(["GET"])
@permission_classes([DenyOperator])
def balances(request):
    module = request.query_params.get("module")
    return Response(accounts_snapshot(module=module))


@extend_schema(responses=OpenApiTypes.OBJECT, tags=["reports"])
@api_view(["GET"])
@permission_classes([DenyOperator])
def debts_report(request):
    return Response(debts_summary())


@extend_schema(parameters=PERIOD_PARAMS, responses=OpenApiTypes.OBJECT, tags=["reports"])
@api_view(["GET"])
@permission_classes([DenyOperator])
def business_orders_report(request):
    date_from, date_to, _ = _period_params(request)
    return Response(business_orders(date_from, date_to))


@extend_schema(
    parameters=PERIOD_PARAMS
    + [OpenApiParameter("module", OpenApiTypes.STR, enum=["EXPRESS", "BUSINESS"], description="Направление")],
    responses=OpenApiTypes.OBJECT,
    tags=["reports"],
)
@api_view(["GET"])
@permission_classes([DenyOperator])
def journal_report(request):
    date_from, date_to, _ = _period_params(request)
    module = request.query_params.get("module") or None
    return Response(journal(date_from, date_to, module=module))


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
    module = request.query_params.get("module") or None
    basis = request.query_params.get("basis", "accrual")
    return Response(breakdown(line, date_from, date_to, payment, module, basis))
