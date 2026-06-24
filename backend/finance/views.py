from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdmin
from .models import Account, AppSettings, Expense, Transfer
from .reports import accounts_snapshot, build_cashflow, build_pnl, business_orders, debts_summary
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


class AppSettingsView(APIView):
    """Singleton settings — readable by all, editable by admins only."""

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH"):
            return [IsAdmin()]
        return [IsAuthenticated()]

    def get(self, request):
        return Response(AppSettingsSerializer(AppSettings.load()).data)

    def put(self, request):
        return self._update(request)

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
            return [IsAuthenticated()]
        return [IsAdmin()]


class ExpenseViewSet(viewsets.ModelViewSet):
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated]

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
    permission_classes = [IsAuthenticated]

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


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pnl_report(request):
    date_from, date_to, payment = _period_params(request)
    tax_rate = request.query_params.get("tax_rate")
    module = request.query_params.get("module") or None
    return Response(build_pnl(date_from, date_to, payment, tax_rate=tax_rate, module=module))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cashflow_report(request):
    date_from, date_to, payment = _period_params(request)
    module = request.query_params.get("module") or None
    return Response(build_cashflow(date_from, date_to, payment, module=module))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def balances(request):
    module = request.query_params.get("module")
    return Response(accounts_snapshot(module=module))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def debts_report(request):
    return Response(debts_summary())


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def business_orders_report(request):
    date_from, date_to, _ = _period_params(request)
    return Response(business_orders(date_from, date_to))
