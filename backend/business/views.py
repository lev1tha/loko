from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from drf_spectacular.utils import extend_schema, inline_serializer

from accounts.permissions import DenyOperator
from .models import Debt, Deposit
from .serializers import DebtSerializer, DepositSerializer


class DepositViewSet(viewsets.ModelViewSet):
    serializer_class = DepositSerializer
    permission_classes = [DenyOperator]

    def get_queryset(self):
        qs = Deposit.objects.select_related("account").all()
        params = self.request.query_params
        status = params.get("status")
        date_from = params.get("from")
        date_to = params.get("to")
        if status:
            qs = qs.filter(status=status)
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        return qs

    def perform_create(self, serializer):
        # Deposits are NOT revenue on creation — they stay HELD until recognized.
        serializer.save(created_by=self.request.user)

    @extend_schema(
        request=inline_serializer("DepositRecognizeRequest", {"date": serializers.DateField(required=False)}),
        responses=DepositSerializer,
    )
    @action(detail=True, methods=["post"])
    def recognize(self, request, pk=None):
        """Признать депозит как выручку."""
        deposit = self.get_object()
        if deposit.status == Deposit.Status.SENT_SUPPLIER:
            return Response(
                {"detail": "Депозит уже отправлен поставщику."}, status=400
            )
        if deposit.status == Deposit.Status.RECOGNIZED:
            return Response({"detail": "Депозит уже признан как выручка."}, status=400)
        deposit.recognize_as_revenue(when=request.data.get("date"))
        return Response(DepositSerializer(deposit).data)

    @extend_schema(
        request=inline_serializer(
            "DepositSendSupplierRequest",
            {"date": serializers.DateField(required=False), "supplier": serializers.CharField(required=False)},
        ),
        responses=DepositSerializer,
    )
    @action(detail=True, methods=["post"], url_path="send-to-supplier")
    def send_to_supplier(self, request, pk=None):
        """Отправить депозит поставщику как предоплату (создаёт расход)."""
        deposit = self.get_object()
        if deposit.status == Deposit.Status.SENT_SUPPLIER:
            return Response({"detail": "Уже отправлен поставщику."}, status=400)
        if deposit.status == Deposit.Status.RECOGNIZED:
            # Признанный депозит — уже выручка; отправка поставщику задвоила бы деньги
            # (выручка пропадает, а отток создаётся). Запрещаем.
            return Response(
                {"detail": "Депозит уже признан как выручка — его нельзя отправить поставщику."},
                status=400,
            )
        deposit.send_to_supplier(
            when=request.data.get("date"), supplier=request.data.get("supplier")
        )
        return Response(DepositSerializer(deposit).data)


class DebtViewSet(viewsets.ModelViewSet):
    serializer_class = DebtSerializer
    permission_classes = [DenyOperator]

    def get_queryset(self):
        qs = Debt.objects.all()
        params = self.request.query_params
        kind = params.get("kind")
        status = params.get("status")
        if kind:
            qs = qs.filter(kind=kind)
        if status:
            qs = qs.filter(status=status)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @extend_schema(request=None, responses=DebtSerializer)
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """Отметить задолженность погашенной."""
        debt = self.get_object()
        debt.status = Debt.Status.CLOSED
        debt.save(update_fields=["status"])
        return Response(DebtSerializer(debt).data)
