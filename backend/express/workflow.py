"""«Процесс работы» и остаток склада — движки для директора (read-only отчёт +
учёт кг). Возвращают plain-dict'ы (как ``finance.reports``).

Прозрачность: за период — кто из сотрудников что сделал (оператор создаёт
заявки, складовщик оприходует позиции ``found_by`` с весом → продажа), что сейчас
в работе и что осталось на «вечерний допоиск» (``WarehouseItem.EVENING``).
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import Sale, WarehouseItem, WarehouseOrder, WarehouseStock
from .serializers import WarehouseItemSerializer, WarehouseOrderSerializer

ZERO = Decimal("0.00")
KG0 = Decimal("0.000")
User = get_user_model()

ACTIVE_LIMIT = 200
DAYS_CAP = 60


def _user_row(u):
    return {
        "id": u.id,
        "name": (u.get_full_name() or u.username),
        "username": u.username,
        "role": u.role,
        "role_display": u.get_role_display(),
        "branch": u.branch_id,
        "branch_name": u.branch.name if u.branch_id else None,
        "orders_created": 0, "items_created": 0,
        "items_found": 0, "kg_found": KG0, "som_found": ZERO,
        "items_not_found": 0, "items_evening": 0, "items_delivered": 0,
    }


def build_workflow(date_from=None, date_to=None, branch_id=None):
    """Сводка по сотрудникам за период + живая доска (в работе / вечерний допоиск).

    Период — по ``created_at`` позиции (заявки) для операторов и по ``updated_at``
    оприходования для складовщиков (позиция FOUND/DELIVERED/NOT_FOUND меняется в
    момент решения). «В работе» и «вечерний допоиск» — всегда текущие, без периода.
    """
    today = timezone.localdate()
    d_from = date_from or today
    d_to = date_to or today
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(timezone.datetime.combine(d_from, timezone.datetime.min.time()), tz)
    end = timezone.make_aware(timezone.datetime.combine(d_to + timedelta(days=1), timezone.datetime.min.time()), tz)

    scope = Q()
    if branch_id:
        scope = Q(order__branch_id=branch_id)

    users = {}

    def row(uid):
        if uid not in users:
            u = User.objects.select_related("branch").get(pk=uid)
            users[uid] = _user_row(u)
        return users[uid]

    # Операторы: созданные заявки/позиции за период.
    # Ожидаемые посылки Kargoosh (EXPECTED) — не работа сотрудников, в счётчики не входят.
    created = (
        WarehouseItem.objects.filter(scope, created_at__gte=start, created_at__lt=end, order__created_by__isnull=False)
        .exclude(status=WarehouseItem.Status.EXPECTED)
        .values("order__created_by").annotate(items=Count("id"), orders=Count("order", distinct=True))
    )
    for r in created:
        u = row(r["order__created_by"])
        u["items_created"] = r["items"]
        u["orders_created"] = r["orders"]

    # Складовщики: решения по позициям за период (found_by).
    decided = (
        WarehouseItem.objects.filter(scope, updated_at__gte=start, updated_at__lt=end, found_by__isnull=False)
        .values("found_by", "status").annotate(n=Count("id"), kg=Sum("weight_kg"), som=Sum("sale__price_som"))
    )
    for r in decided:
        u = row(r["found_by"])
        st = r["status"]
        if st in WarehouseItem.FINANCIAL:
            u["items_found"] += r["n"]
            u["kg_found"] += r["kg"] or KG0
            u["som_found"] += r["som"] or ZERO
            if st == WarehouseItem.Status.DELIVERED:
                u["items_delivered"] += r["n"]
        elif st == WarehouseItem.Status.NOT_FOUND:
            u["items_not_found"] += r["n"]
        elif st == WarehouseItem.Status.EVENING:
            u["items_evening"] += r["n"]

    employees = sorted(users.values(), key=lambda x: (-(x["items_found"] + x["items_created"]), x["name"]))
    for e in employees:
        e["kg_found"] = str(e["kg_found"].quantize(KG0))
        e["som_found"] = str(e["som_found"].quantize(ZERO))

    # Живая доска: заявки с позициями «в поиске» + вечерний допоиск.
    active_qs = (
        WarehouseOrder.objects.filter(items__status=WarehouseItem.Status.IN_SEARCH)
        .select_related("branch", "created_by", "assigned_to").prefetch_related("items", "items__sale")
        .distinct().order_by("-created_at")
    )
    evening_qs = (
        WarehouseItem.objects.filter(status=WarehouseItem.Status.EVENING)
        .select_related("order", "order__branch", "order__created_by", "sale").order_by("id")
    )
    if branch_id:
        active_qs = active_qs.filter(branch_id=branch_id)
        evening_qs = evening_qs.filter(order__branch_id=branch_id)
    active_count = active_qs.count()

    period_items = WarehouseItem.objects.filter(scope, updated_at__gte=start, updated_at__lt=end)
    fin = period_items.filter(status__in=WarehouseItem.FINANCIAL).aggregate(n=Count("id"), kg=Sum("weight_kg"), som=Sum("sale__price_som"))
    totals = {
        "from": d_from.isoformat(), "to": d_to.isoformat(),
        "orders_created": WarehouseOrder.objects.filter(
            Q(branch_id=branch_id) if branch_id else Q(), created_at__gte=start, created_at__lt=end)
            .exclude(origin=WarehouseOrder.Origin.KARGO).count(),
        "items_created": WarehouseItem.objects.filter(scope, created_at__gte=start, created_at__lt=end)
            .exclude(status=WarehouseItem.Status.EXPECTED).count(),
        "expected_now": WarehouseItem.objects.filter(scope, status=WarehouseItem.Status.EXPECTED).count(),
        "items_found": fin["n"] or 0,
        "kg_found": str((fin["kg"] or KG0).quantize(KG0)),
        "som_found": str((fin["som"] or ZERO).quantize(ZERO)),
        "items_not_found": period_items.filter(status=WarehouseItem.Status.NOT_FOUND).count(),
        "in_search_now": WarehouseItem.objects.filter(scope, status=WarehouseItem.Status.IN_SEARCH).count(),
        "active_orders_now": active_count,
        "evening_now": evening_qs.count(),
    }
    return {
        "totals": totals,
        "employees": employees,
        "active_orders": WarehouseOrderSerializer(active_qs[:ACTIVE_LIMIT], many=True).data,
        "active_truncated": active_count > ACTIVE_LIMIT,
        "evening": WarehouseItemSerializer(evening_qs, many=True).data,
    }


# ---------------------------------------------------------------------------
# Остаток веса на складе
# ---------------------------------------------------------------------------

def _consumption_qs(branch_id, since):
    """Расход склада: вес, который склад Loko оприходовал на этой точке — позиции
    склада (в т.ч. ожидаемые посылки с сайта, привязанные к его записям) и прямые
    продажи кассира. Историю, перенесённую из Kargoosh, и заказы, взвешенные в
    админке сайта (без складской позиции Loko), не считаем."""
    return Sale.objects.filter(branch_id=branch_id, date__gte=since, weight_kg__isnull=False).filter(
        Q(warehouse_item__status__in=list(WarehouseItem.FINANCIAL))
        | Q(legacy_kargo_id__isnull=True, delivery_status__isnull=True)
    )


def build_stock(branch_id):
    """Остаток кг на складе филиала + дневная лента (приход / расход / остаток)."""
    entries = list(WarehouseStock.objects.filter(branch_id=branch_id).select_related("created_by").order_by("date", "id"))
    if not entries:
        return {"branch": branch_id, "since": None, "balance_kg": "0.000", "added_kg": "0.000",
                "consumed_kg": "0.000", "days": [], "entries": [], "workers": []}
    since = entries[0].date
    today = timezone.localdate()

    added_by_day = defaultdict(lambda: KG0)
    for e in entries:
        added_by_day[e.date] += e.kg
    consumed_by_day = defaultdict(lambda: KG0)
    for r in _consumption_qs(branch_id, since).values("date").annotate(kg=Sum("weight_kg")):
        consumed_by_day[r["date"]] = r["kg"] or KG0

    balance = KG0
    days = []
    d = since
    while d <= today:
        a, c = added_by_day.get(d, KG0), consumed_by_day.get(d, KG0)
        balance += a - c
        days.append({"date": d.isoformat(), "added_kg": str(a.quantize(KG0)), "consumed_kg": str(c.quantize(KG0)),
                     "balance_kg": str(balance.quantize(KG0))})
        d += timedelta(days=1)
    # Продажи «в будущем» (дата больше сегодня) — в остаток, но не в ленту.
    future = sum((v for k, v in consumed_by_day.items() if k > today), KG0)
    balance -= future
    added_total = sum((e.kg for e in entries), KG0)
    consumed_total = sum(consumed_by_day.values(), KG0)

    # Кто выдал вес: по складовщику, оприходовавшему позицию (found_by). Прямые продажи
    # кассира без складской позиции — отдельной строкой.
    workers = {}
    cons = _consumption_qs(branch_id, since).select_related("warehouse_item__found_by")
    for sale in cons.only("weight_kg", "date", "warehouse_item"):
        item = getattr(sale, "warehouse_item", None)
        u = item.found_by if item is not None else None
        key = u.id if u else 0
        w = workers.setdefault(key, {
            "id": u.id if u else None,
            "name": (u.get_full_name() or u.username) if u else "Без склада (прямая продажа)",
            "role": u.get_role_display() if u else "",
            "kg": KG0, "count": 0, "kg_today": KG0, "count_today": 0,
        })
        w["kg"] += sale.weight_kg or KG0
        w["count"] += 1
        if sale.date == today:
            w["kg_today"] += sale.weight_kg or KG0
            w["count_today"] += 1
    workers = sorted(workers.values(), key=lambda w: -w["kg"])
    for w in workers:
        w["kg"] = str(w["kg"].quantize(KG0)); w["kg_today"] = str(w["kg_today"].quantize(KG0))

    return {
        "workers": workers,
        "branch": branch_id,
        "since": since.isoformat(),
        "balance_kg": str(balance.quantize(KG0)),
        "added_kg": str(added_total.quantize(KG0)),
        "consumed_kg": str(consumed_total.quantize(KG0)),
        "days": list(reversed(days))[:DAYS_CAP],
        "entries": [
            {"id": e.id, "date": e.date.isoformat(), "kind": e.kind, "kind_display": e.get_kind_display(),
             "kg": str(e.kg), "note": e.note,
             "created_by_name": (e.created_by.get_full_name() or e.created_by.username) if e.created_by_id else None,
             "created_at": e.created_at}
            for e in reversed(entries)
        ][:200],
    }

