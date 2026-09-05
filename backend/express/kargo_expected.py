"""Ожидаемые посылки: заказы Kargoosh «в пути» → позиции на доске склада Loko.

Как только сайт узнаёт трек-номер (отправка из Китая), импорт создаёт продажу
``delivery_status=TRANSIT``. Здесь из таких продаж (отправленных не раньше
``EXPECTED_DAYS`` дней назад) делаем заявку ``origin=KARGO`` на филиал и позицию
``EXPECTED`` с привязкой к продаже. Складовщик видит, что должно приехать, и при
оприходовании ОБНОВЛЯЕТ ту же продажу (``WarehouseItem.receive``) — дублей нет.

Филиал для заявки: точка Loko с тем же регионом Kargoosh (``Branch.legacy_kargo_region``),
где есть складовщик; иначе филиал продажи (как импортировано).
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from finance.models import Branch

from .models import Client, DeliveryStatus, Sale, WarehouseItem, WarehouseOrder

EXPECTED_DAYS = 30      # берём на доску отправленные за последние N дней
STALE_DAYS = 60         # ожидаемое старше — с доски убираем (в отчётах остаётся)


def target_branch(sale_branch):
    """Точка Loko для ожидаемой посылки по региону Kargoosh."""
    if sale_branch is None:
        return Branch.resolve_default()
    region = sale_branch.legacy_kargo_region
    if region:
        User = get_user_model()
        with_wh = (Branch.objects.filter(legacy_kargo_region=region, is_active=True)
                   .annotate(n=Count("users", filter=Q(users__role=User.Role.WAREHOUSE, users__is_active=True)))
                   .order_by("-n", "id").first())
        if with_wh is not None:
            return with_wh
    return sale_branch


def _open_kargo_order(code, branch, client):
    # Ищем по позициям, а не по JSON-полю: contains недоступен на SQLite (dev).
    order = (WarehouseOrder.objects
             .filter(origin=WarehouseOrder.Origin.KARGO, branch=branch, items__client_code__iexact=code)
             .exclude(status__in=[WarehouseOrder.Status.ISSUED, WarehouseOrder.Status.CANCELLED])
             .order_by("-id").first())
    if order is None:
        order = WarehouseOrder.objects.create(
            branch=branch, client=client, origin=WarehouseOrder.Origin.KARGO,
            created_by=WarehouseOrder.resolve_operator(branch), client_codes=[code],
            comment="Ожидаемые посылки из Kargoosh",
        )
    return order


def sync_expected(stdout=None):
    """Создать/обновить/убрать ожидаемые позиции. Возвращает счётчики."""
    today = timezone.localdate()
    since = today - timedelta(days=EXPECTED_DAYS)
    stats = {"expected_created": 0, "expected_arrived": 0, "expected_removed": 0}

    with transaction.atomic():
        # 1) новые ожидаемые: TRANSIT-продажи Kargoosh без позиции
        qs = (Sale.objects.filter(delivery_status=DeliveryStatus.TRANSIT, legacy_kargo_id__isnull=False,
                                  warehouse_item__isnull=True, shipment_date__gte=since)
              .exclude(client_code="").select_related("branch").order_by("id"))
        branch_cache, client_cache = {}, {}
        for sale in qs:
            code = sale.client_code.strip().upper()
            b = branch_cache.get(sale.branch_id)
            if b is None:
                b = branch_cache[sale.branch_id] = target_branch(sale.branch)
            if b is None:
                continue
            if code not in client_cache:
                client_cache[code] = Client.objects.filter(code=code).first()
            order = _open_kargo_order(code, b, client_cache[code])
            WarehouseItem.objects.create(order=order, client_code=code, status=WarehouseItem.Status.EXPECTED, sale=sale)
            stats["expected_created"] += 1

        # 2) ожидаемые, которые сайт уже взвесил/выдал сам (админка Kargoosh) — отражаем
        for it in WarehouseItem.objects.filter(status=WarehouseItem.Status.EXPECTED, sale__isnull=False) \
                .exclude(sale__delivery_status=DeliveryStatus.TRANSIT).select_related("sale"):
            it.weight_kg = it.sale.weight_kg
            it.status = WarehouseItem.Status.DELIVERED if it.sale.delivery_status == DeliveryStatus.DELIVERED else WarehouseItem.Status.FOUND
            it.save(update_fields=["weight_kg", "status", "updated_at"])
            stats["expected_arrived"] += 1

        # 3) протухшие ожидаемые (не приехали за STALE_DAYS) — с доски убираем
        stale = WarehouseItem.objects.filter(status=WarehouseItem.Status.EXPECTED, sale__isnull=False,
                                             sale__shipment_date__lt=today - timedelta(days=STALE_DAYS))
        order_ids = set(stale.values_list("order_id", flat=True))
        stats["expected_removed"] = stale.delete()[0]
        WarehouseOrder.objects.filter(id__in=order_ids, origin=WarehouseOrder.Origin.KARGO, items__isnull=True).delete()

    if stdout:
        stdout.write(f"  ожидаемые посылки: +{stats['expected_created']} новых, {stats['expected_arrived']} приехали через сайт, "
                     f"{stats['expected_removed']} протухших убрано")
    return stats
