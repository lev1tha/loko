"""Перенос существующих заявок склада в позиции (WarehouseItem).

До двухэтапного учёта заявка хранила коды списком (``client_codes``) и была связана
с уже созданными продажами (старый поток: продажа → заявка). Здесь для каждой заявки
создаём построчные позиции и, если по коду есть продажа, связываем её и помечаем
FOUND/DELIVERED. Идемпотентно: заявки, у которых позиции уже есть, пропускаем.
"""
from django.db import migrations
from django.utils import timezone


def forwards(apps, schema_editor):
    WarehouseOrder = apps.get_model("express", "WarehouseOrder")
    WarehouseItem = apps.get_model("express", "WarehouseItem")

    for order in WarehouseOrder.objects.all():
        if order.items.exists():
            continue
        # Продажи заявки — по коду клиента (для связывания оприходованных позиций).
        sales_by_code = {}
        for s in order.sales.all():
            sales_by_code.setdefault(str(s.client_code).strip(), s)

        now = timezone.now()
        for raw in (order.client_codes or []):
            code = str(raw).strip()
            if not code:
                continue
            item = WarehouseItem(
                order=order, client_code=code, created_at=now, updated_at=now,
            )
            sale = sales_by_code.get(code)
            if sale is not None:
                item.sale = sale
                item.weight_kg = sale.weight_kg
                item.status = "DELIVERED" if order.status == "ISSUED" else "FOUND"
            elif order.status == "CANCELLED":
                item.status = "NOT_FOUND"
                item.reason = "перенос: заявка была отменена"
            elif order.status == "NOT_FOUND":
                item.status = "NOT_FOUND"
            else:
                item.status = "IN_SEARCH"
            item.save()


def backwards(apps, schema_editor):
    # Обратно позиции просто удаляем (заявки/продажи остаются нетронутыми).
    WarehouseItem = apps.get_model("express", "WarehouseItem")
    WarehouseItem.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("express", "0008_warehouseitem"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
