from decimal import Decimal, InvalidOperation

from django.db.models import Count, Sum
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

from accounts.permissions import SalesAccess
from finance.models import Account, AppSettings
from .models import Sale
from .serializers import OperatorSaleSerializer, SaleSerializer

ZERO = Decimal("0.00")


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("from", OpenApiTypes.DATE, description="Начало периода"),
            OpenApiParameter("to", OpenApiTypes.DATE, description="Конец периода"),
            OpenApiParameter("payment", OpenApiTypes.STR, enum=["all", "cash", "noncash"], description="Вид оплаты"),
            OpenApiParameter("search", OpenApiTypes.STR, description="Поиск по коду клиента"),
        ]
    )
)
class SaleViewSet(viewsets.ModelViewSet):
    serializer_class = SaleSerializer
    # Managers/admins: full access. Operators («Сотрудник»): create + quote +
    # the minimal account picker only (enforced per-action by SalesAccess).
    permission_classes = [SalesAccess]

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
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

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
        request=inline_serializer(
            "SaleQuoteRequest",
            {"weight_kg": serializers.DecimalField(max_digits=10, decimal_places=3)},
        ),
        responses=OpenApiTypes.OBJECT,
    )
    @action(detail=False, methods=["post"], url_path="quote")
    def quote(self, request):
        """Live price/cost/margin preview without persisting a sale."""
        cfg = AppSettings.load()
        try:
            weight = Decimal(str(request.data.get("weight_kg", "0")))
        except (TypeError, ValueError, InvalidOperation):
            weight = ZERO
        # Отсекаем не-числа, отрицательные и абсурдно большие значения (иначе
        # quantize переполняется → 500). Верх — ёмкость поля weight_kg.
        if not weight.is_finite() or weight < 0 or weight > Decimal("9999999.999"):
            weight = ZERO
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
