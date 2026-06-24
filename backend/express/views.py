from decimal import Decimal

from django.db.models import Count, Sum
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from finance.models import AppSettings
from .models import Sale
from .serializers import SaleSerializer

ZERO = Decimal("0.00")


class SaleViewSet(viewsets.ModelViewSet):
    serializer_class = SaleSerializer
    permission_classes = [IsAuthenticated]

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

    @action(detail=False, methods=["post"], url_path="quote")
    def quote(self, request):
        """Live price/cost/margin preview without persisting a sale."""
        cfg = AppSettings.load()
        try:
            weight = Decimal(str(request.data.get("weight_kg", "0")))
        except (TypeError, ValueError):
            weight = ZERO
        price = (weight * cfg.price_per_kg_usd * cfg.usd_rate_som).quantize(ZERO)
        cost = (weight * cfg.base_cost_per_kg_som).quantize(ZERO)
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
