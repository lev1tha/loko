"""Обратный мост Loko → Kargoosh: продажи, созданные в Loko, попадают в таблицу
``orders`` сайта kargoosh.kg, и клиент видит их в своём кабинете.

Поток: сигнал ``post_save`` на ``Sale`` / ``WarehouseOrder`` помечает продажу
``kargo_sync_pending`` (дёшево, без внешних соединений) и, если включено
``KARGO_PUSH_IMMEDIATE``, пробует отправить сразу. Всё, что не ушло, добирает
``manage.py push_kargoosh`` (и ``import_kargoosh --incremental`` перед импортом).

Что отправляем: продажи Express, рождённые в Loko (``legacy_kargo_id`` пуст
или уже проставлен этим мостом), с кодом клиента. Строка в Kargoosh:
  * трек — ``tracking_number`` продажи, иначе ``LOKO-<id>`` (в Kargoosh трек
    обязателен и уникален);
  * статус: складская позиция FOUND → 2 «на складе» (dt_arrival), заявка
    выдана (ISSUED) → 3 «отдан» (dt_pickup); продажи Kargo-цикла (через
    /api/kargo/) — по ``delivery_status``; прямая продажа кассира → 3;
  * филиал → ``fk_i_admin_id`` через ``admin.s_region``; без региона —
    ``KARGO_DEFAULT_ADMIN_ID``.
Ответный ``pk_i_id`` сохраняем в ``legacy_kargo_id``, чтобы импорт видел ту же
строку и НЕ перезаписывал её (для Loko-строк Loko — главный).
"""
import logging
from datetime import datetime, time

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import DeliveryStatus, Sale, WarehouseItem, WarehouseOrder

log = logging.getLogger(__name__)

STATUS_CODE = {DeliveryStatus.TRANSIT: 1, DeliveryStatus.ARRIVED: 2, DeliveryStatus.DELIVERED: 3}


def enabled() -> bool:
    return bool(getattr(settings, "KARGO_DB_HOST", ""))


def connect():
    import pymysql
    return pymysql.connect(
        host=settings.KARGO_DB_HOST, port=settings.KARGO_DB_PORT,
        user=settings.KARGO_DB_USER, password=settings.KARGO_DB_PASSWORD,
        database=settings.KARGO_DB_NAME, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=5, autocommit=True,
    )


def is_loko_origin(sale) -> bool:
    """Продажей владеет Loko: создана здесь, уже отправлялась мостом, либо это
    ожидаемая посылка Kargoosh, которую оприходовал склад Loko."""
    if sale.legacy_kargo_id is None or sale.kargo_pushed_at is not None:
        return True
    item = getattr(sale, "warehouse_item", None)
    return item is not None and item.status in WarehouseItem.FINANCIAL


def _dt(d):
    """date → naive datetime (MySQL DATETIME, локальное время сервера Kargoosh)."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return timezone.localtime(d).replace(tzinfo=None) if timezone.is_aware(d) else d
    return datetime.combine(d, time(12, 0))


def sale_row(sale, admin_by_region, default_admin):
    """Словарь колонок ``orders`` для продажи (без pk). None → продажу не отправляем."""
    code = (sale.client_code or "").strip().upper()
    if not code or sale.account.module != "EXPRESS" or not is_loko_origin(sale):
        return None
    track = (sale.tracking_number or "").strip() or f"LOKO-{sale.id}"
    item = getattr(sale, "warehouse_item", None)
    if sale.delivery_status:                          # Kargo-цикл через /api/kargo/
        status = STATUS_CODE[sale.delivery_status]
        arrival, pickup, shipment = sale.arrival_date, (sale.payment_date if status == 3 else None), sale.shipment_date
    elif item is not None:                            # склад Loko
        issued = item.order.status == WarehouseOrder.Status.ISSUED or item.status == WarehouseItem.Status.DELIVERED
        status = 3 if issued else 2
        arrival, pickup, shipment = sale.date, (timezone.localtime(item.order.updated_at).date() if issued else None), None
    else:                                             # прямая продажа кассира — груз уже у клиента
        status, arrival, pickup, shipment = 3, sale.date, (sale.payment_date or sale.date), None
    region = (sale.branch.legacy_kargo_region if sale.branch_id else "") or ""
    return {
        "fk_i_admin_id": admin_by_region.get(region, default_admin),
        "s_user_code": code[:15],
        "s_tracking_number": track[:100],
        "i_quantity": sale.places or 1,
        "i_weight": sale.weight_kg or 0,
        "i_price": sale.price_som or 0,
        "dt_shipment": _dt(shipment),
        "dt_arrival": _dt(arrival),
        "dt_pickup": _dt(pickup),
        "i_status": status,
        "s_discount_price": "",
    }


def _admins(cur):
    cur.execute("SELECT pk_i_id, s_region FROM admin WHERE s_region IS NOT NULL AND s_region<>''")
    return {r["s_region"].strip(): r["pk_i_id"] for r in cur.fetchall()}


def push_sale(sale, cur, admin_by_region, default_admin):
    """INSERT или UPDATE одной продажи. Возвращает 'inserted' | 'updated' | 'skipped'."""
    row = sale_row(sale, admin_by_region, default_admin)
    if row is None:
        Sale.objects.filter(pk=sale.pk).update(kargo_sync_pending=False)
        return "skipped"
    cols = list(row)
    if sale.legacy_kargo_id:
        sets = ", ".join(f"{c}=%s" for c in cols)
        cur.execute(f"UPDATE orders SET {sets} WHERE pk_i_id=%s", [row[c] for c in cols] + [sale.legacy_kargo_id])
        kind = "updated"
        pk = sale.legacy_kargo_id
    else:
        # Трек уже есть в Kargoosh (например, PHP-админка успела завести) — обновляем ту строку.
        cur.execute("SELECT pk_i_id FROM orders WHERE s_tracking_number=%s", (row["s_tracking_number"],))
        found = cur.fetchone()
        if found:
            sets = ", ".join(f"{c}=%s" for c in cols)
            cur.execute(f"UPDATE orders SET {sets} WHERE pk_i_id=%s", [row[c] for c in cols] + [found["pk_i_id"]])
            pk, kind = found["pk_i_id"], "updated"
        else:
            ph = ", ".join(["%s"] * len(cols))
            cur.execute(f"INSERT INTO orders ({', '.join(cols)}) VALUES ({ph})", [row[c] for c in cols])
            pk, kind = cur.lastrowid, "inserted"
    Sale.objects.filter(pk=sale.pk).update(
        legacy_kargo_id=pk, kargo_sync_pending=False, kargo_pushed_at=timezone.now(),
    )
    return kind


def pending_qs():
    return (
        Sale.objects.filter(kargo_sync_pending=True)
        .select_related("account", "branch", "warehouse_item", "warehouse_item__order")
        .order_by("id")
    )


def push_pending(limit=500, conn=None):
    """Отправить все ожидающие продажи. Возвращает счётчики; при недоступности
    MySQL — {'error': ...} (флаги pending остаются, доберём следующим прогоном)."""
    stats = {"inserted": 0, "updated": 0, "skipped": 0, "failed": 0}
    qs = list(pending_qs()[:limit])
    if not qs:
        return stats
    own = conn is None
    try:
        conn = conn or connect()
    except Exception as exc:  # noqa: BLE001
        log.warning("kargo push: MySQL недоступен: %s", exc)
        return {**stats, "error": str(exc)}
    try:
        with conn.cursor() as cur:
            admins = _admins(cur)
            for sale in qs:
                try:
                    stats[push_sale(sale, cur, admins, settings.KARGO_DEFAULT_ADMIN_ID)] += 1
                except Exception as exc:  # noqa: BLE001 — одна битая строка не должна стопорить остальные
                    log.warning("kargo push: продажа %s не отправлена: %s", sale.pk, exc)
                    stats["failed"] += 1
    finally:
        if own:
            conn.close()
    return stats


# ---------------------------------------------------------------------------
# Сигналы: помечаем pending; при KARGO_PUSH_IMMEDIATE пробуем отправить сразу
# после коммита (best effort — сбой внешней БД не ломает запрос).
# ---------------------------------------------------------------------------

def _mark(sale_ids):
    sale_ids = [i for i in sale_ids if i]
    if not sale_ids:
        return
    Sale.objects.filter(pk__in=sale_ids).filter(
        Q(legacy_kargo_id__isnull=True) | Q(kargo_pushed_at__isnull=False)
        | Q(warehouse_item__status__in=list(WarehouseItem.FINANCIAL)),
        account__module="EXPRESS",
    ).exclude(client_code="").update(kargo_sync_pending=True)
    if enabled() and getattr(settings, "KARGO_PUSH_IMMEDIATE", True):
        transaction.on_commit(lambda: push_pending(limit=50))


@receiver(post_save, sender=Sale, dispatch_uid="kargo_push_sale")
def _on_sale_saved(sender, instance, **kwargs):
    if kwargs.get("raw"):
        return
    _mark([instance.pk])


@receiver(post_save, sender=WarehouseItem, dispatch_uid="kargo_push_item")
def _on_item_saved(sender, instance, **kwargs):
    """Позиция привязалась к продаже / сменила статус → переотправить продажу."""
    if kwargs.get("raw") or not instance.sale_id:
        return
    _mark([instance.sale_id])


@receiver(post_save, sender=WarehouseOrder, dispatch_uid="kargo_push_order")
def _on_order_saved(sender, instance, **kwargs):
    """Выдача заявки (ISSUED) → в Kargoosh статус «отдан» у всех её продаж."""
    if kwargs.get("raw") or instance.status != WarehouseOrder.Status.ISSUED:
        return
    _mark(list(WarehouseItem.objects.filter(order=instance, sale__isnull=False).values_list("sale_id", flat=True)))
