"""Ожидаемые посылки Kargoosh на доске склада: без дублей продаж."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APITestCase

from express import kargo_push
from express.kargo_expected import sync_expected
from express.models import Client, DeliveryStatus, Sale, WarehouseItem, WarehouseOrder
from finance.models import Account, AppSettings, Branch

User = get_user_model()


class Base(APITestCase):
    def setUp(self):
        cache.clear()
        cfg = AppSettings.load(); cfg.price_per_kg_usd = Decimal("3"); cfg.usd_rate_som = Decimal("90"); cfg.base_cost_per_kg_som = Decimal("100"); cfg.save()
        self.acc = Account.objects.create(name="Касса Kargo", kind="CASH", currency="KGS", module="EXPRESS", legacy_kargo_card_id=1)
        self.kargo_osh = Branch.objects.create(name="Kargo · Ош", legacy_kargo_region="Ош")          # как создаёт импорт
        self.loko_osh = Branch.objects.create(name="Loko Гульчинская", legacy_kargo_region="Ош", is_default=True)  # реальная точка
        self.wh = User.objects.create_user("wh", password="x", role=User.Role.WAREHOUSE, branch=self.loko_osh)
        self.op = User.objects.create_user("op", password="x", role=User.Role.OPERATOR, branch=self.loko_osh)
        self.client_k = Client.objects.create(phone="700123456", code="AL-12345", legacy_kargo_id=7)

    def transit_sale(self, track, days_ago=3, code="AL-12345", legacy=None):
        d = timezone.localdate() - timedelta(days=days_ago)
        return Sale.objects.create(
            client_code=code, amount_mode="DIRECT", account=self.acc, branch=self.kargo_osh, price_som=Decimal("0"),
            paid_som=Decimal("0"), cost_is_manual=True, date=d, shipment_date=d, tracking_number=track,
            delivery_status=DeliveryStatus.TRANSIT, legacy_kargo_id=legacy or (100000 + hash(track) % 100000),
        )


class SyncTests(Base):
    def test_creates_expected_items_on_loko_branch_with_warehouse(self):
        s1 = self.transit_sale("T1"); s2 = self.transit_sale("T2")
        self.transit_sale("OLD", days_ago=45)                        # старше 30 дней — не берём
        stats = sync_expected()
        self.assertEqual(stats["expected_created"], 2)
        items = WarehouseItem.objects.filter(status=WarehouseItem.Status.EXPECTED)
        self.assertEqual({i.sale_id for i in items}, {s1.id, s2.id})
        order = items.first().order
        self.assertEqual((order.origin, order.branch, order.created_by, order.client), ("KARGO", self.loko_osh, self.op, self.client_k))
        self.assertEqual(items.values("order").distinct().count(), 1)  # одна заявка на код
        # повторный прогон ничего не дублирует
        self.assertEqual(sync_expected()["expected_created"], 0)

    def test_arrived_via_site_and_stale_cleanup(self):
        s = self.transit_sale("T3"); sync_expected()
        Sale.objects.filter(pk=s.pk).update(delivery_status=DeliveryStatus.ARRIVED, weight_kg=Decimal("2"), price_som=Decimal("540"))
        st = sync_expected()
        self.assertEqual(st["expected_arrived"], 1)
        self.assertEqual(WarehouseItem.objects.get(sale=s).status, WarehouseItem.Status.FOUND)
        old = self.transit_sale("T4", days_ago=20); sync_expected()
        Sale.objects.filter(pk=old.pk).update(shipment_date=timezone.localdate() - timedelta(days=70))
        st = sync_expected()
        self.assertEqual(st["expected_removed"], 1)
        self.assertFalse(WarehouseItem.objects.filter(sale=old).exists())


class BoardAndReceiveTests(Base):
    def test_warehouse_sees_expected_and_receive_updates_same_sale(self):
        s = self.transit_sale("T5", legacy=555001); sync_expected()
        item = WarehouseItem.objects.get(sale=s)
        self.client.force_authenticate(self.wh)
        r = self.client.get("/api/warehouse-items/", {"status": "EXPECTED"})
        self.assertEqual([i["tracking_number"] for i in r.data["results"]], ["T5"])
        r = self.client.get("/api/warehouse-orders/")
        self.assertEqual([o["origin"] for o in r.data["results"]], ["KARGO"])
        before = Sale.objects.count()
        r = self.client.post(f"/api/warehouse-items/{item.id}/receive/", {"weight_kg": "2", "account": self.acc.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Sale.objects.count(), before)                # новой продажи НЕТ
        s.refresh_from_db()
        self.assertEqual((s.weight_kg, s.price_som, s.paid_som, s.delivery_status, s.legacy_kargo_id, s.branch, s.created_by),
                         (Decimal("2.000"), Decimal("540.00"), Decimal("0.00"), DeliveryStatus.ARRIVED, 555001, self.loko_osh, self.op))
        self.assertEqual(s.cost_som, Decimal("200.00"))
        self.assertTrue(kargo_push.is_loko_origin(Sale.objects.select_related("warehouse_item").get(pk=s.pk)))
        self.assertTrue(Sale.objects.get(pk=s.pk).kargo_sync_pending)   # уйдёт на сайт как статус 2
        row = kargo_push.sale_row(Sale.objects.select_related("account", "branch", "warehouse_item__order").get(pk=s.pk), {"Ош": 2}, 2)
        self.assertEqual((row["i_status"], row["s_tracking_number"], row["i_weight"]), (2, "T5", Decimal("2.000")))
        # выдача: оплата фиксируется, статус 3
        order = item.order
        for st in ("IN_PROGRESS", "READY"):
            self.client.post(f"/api/warehouse-orders/{order.id}/status/", {"status": st}, format="json")
        adm = User.objects.create_user("adm", password="x", role=User.Role.ADMIN)
        self.client.force_authenticate(adm)
        r = self.client.post(f"/api/warehouse-orders/{order.id}/status/", {"status": "ISSUED"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        s.refresh_from_db(); item.refresh_from_db()
        self.assertEqual((s.delivery_status, s.paid_som, s.payment_date, item.status), (DeliveryStatus.DELIVERED, Decimal("540.00"), timezone.localdate(), WarehouseItem.Status.DELIVERED))

    def test_qr_intake_adopts_expected_items(self):
        s = self.transit_sale("T6"); sync_expected()
        kargo_order = WarehouseItem.objects.get(sale=s).order
        r = self.client.post("/api/public/intake/", {"branch": self.loko_osh.id, "phone": "700123456", "name": "Айбек", "client_codes": ["al-12345"]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        item = WarehouseItem.objects.get(sale=s)
        self.assertEqual((item.status, item.order.origin, item.order.client), (WarehouseItem.Status.IN_SEARCH, "CLIENT", self.client_k))
        self.assertFalse(WarehouseOrder.objects.filter(pk=kargo_order.pk).exists())   # пустая заявка моста удалена
        self.assertEqual(WarehouseItem.objects.filter(client_code__iexact="AL-12345").count(), 1)  # без пустого дубля

    def test_plain_receive_without_expected_still_creates_sale(self):
        o = WarehouseOrder.objects.create(branch=self.loko_osh, created_by=self.op, client_codes=["ZZ-1"])
        it = WarehouseItem.objects.create(order=o, client_code="ZZ-1")
        self.client.force_authenticate(self.wh)
        r = self.client.post(f"/api/warehouse-items/{it.id}/receive/", {"weight_kg": "1", "account": self.acc.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Sale.objects.filter(client_code="ZZ-1").count(), 1)
