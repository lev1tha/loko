"""Обратный мост Loko → Kargoosh (kargo_push): маппинг строки, флаги, охрана импорта."""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from express import kargo_push
from express.models import Client, Sale, WarehouseItem, WarehouseOrder
from finance.models import Account, AppSettings, Branch

User = get_user_model()


class FakeCursor:
    """Минимальный MySQL-курсор: запоминает SQL, отдаёт admin-справочник и id вставки."""

    def __init__(self, existing_track=None):
        self.sql = []
        self.existing_track = existing_track
        self.lastrowid = 0
        self._next = None

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def execute(self, sql, params=None):
        self.sql.append((sql, list(params) if params else []))
        if sql.startswith("SELECT pk_i_id, s_region FROM admin"):
            self._next = [{"pk_i_id": 2, "s_region": "Ош"}, {"pk_i_id": 4, "s_region": "Бишкек"}]
        elif sql.startswith("SELECT pk_i_id FROM orders WHERE s_tracking_number"):
            self._next = [{"pk_i_id": 777}] if params and params[0] == self.existing_track else []
        elif sql.startswith("INSERT"):
            self.lastrowid = 900001 + sum(1 for s, _ in self.sql if s.startswith("INSERT")) - 1
            self._next = []
        else:
            self._next = []

    def fetchall(self): return self._next
    def fetchone(self): return self._next[0] if self._next else None


class FakeConn:
    def __init__(self, cursor): self._c = cursor
    def cursor(self): return self._c
    def close(self): pass


class Base(APITestCase):
    def setUp(self):
        cfg = AppSettings.load(); cfg.price_per_kg_usd = Decimal("3"); cfg.usd_rate_som = Decimal("90"); cfg.save()
        self.acc = Account.objects.create(name="Нал", kind="CASH", currency="KGS", module="EXPRESS")
        self.b_osh = Branch.objects.create(name="Kargo · Ош", legacy_kargo_region="Ош")
        self.b_loko = Branch.objects.create(name="Loko Гульчинская", is_default=True)
        self.op = User.objects.create_user("op", password="x", role=User.Role.OPERATOR, branch=self.b_loko)
        self.wh = User.objects.create_user("wh", password="x", role=User.Role.WAREHOUSE, branch=self.b_loko)
        Client.objects.create(phone="700123456", code="AL-12345", legacy_kargo_id=7)

    def _received(self, code="AL-12345", track=None, branch=None):
        o = WarehouseOrder.objects.create(branch=branch or self.b_loko, created_by=self.op, client_codes=[code])
        it = WarehouseItem.objects.create(order=o, client_code=code)
        it.receive("2", self.acc, by_user=self.wh, tracking_number=track)
        return o, it, Sale.objects.get(pk=it.sale_id)


class MappingTests(Base):
    def test_warehouse_receive_maps_to_arrived(self):
        o, it, s = self._received(track="YT1")
        self.assertTrue(Sale.objects.get(pk=s.pk).kargo_sync_pending)  # сигнал пометил
        row = kargo_push.sale_row(Sale.objects.select_related("account", "branch", "warehouse_item__order").get(pk=s.pk), {"Ош": 2}, 2)
        self.assertEqual((row["s_user_code"], row["s_tracking_number"], row["i_status"], row["fk_i_admin_id"]), ("AL-12345", "YT1", 2, 2))
        self.assertEqual((row["i_weight"], row["i_price"]), (Decimal("2.000"), Decimal("540.00")))
        self.assertEqual(row["dt_arrival"].date(), timezone.localdate())
        self.assertIsNone(row["dt_pickup"])

    def test_issued_order_maps_to_delivered_and_marks_pending_again(self):
        o, it, s = self._received()
        Sale.objects.filter(pk=s.pk).update(kargo_sync_pending=False)
        o.status = WarehouseOrder.Status.ISSUED
        o.save()
        s = Sale.objects.select_related("account", "branch", "warehouse_item__order").get(pk=s.pk)
        self.assertTrue(s.kargo_sync_pending)
        row = kargo_push.sale_row(s, {}, 2)
        self.assertEqual((row["i_status"], row["s_tracking_number"]), (3, f"LOKO-{s.id}"))
        self.assertIsNotNone(row["dt_pickup"])

    def test_branch_without_region_uses_default_admin(self):
        o, it, s = self._received(branch=self.b_loko)
        row = kargo_push.sale_row(Sale.objects.select_related("account", "branch", "warehouse_item__order").get(pk=s.pk), {"Ош": 2, "Бишкек": 4}, 5)
        self.assertEqual(row["fk_i_admin_id"], 5)
        o2, it2, s2 = self._received(code="AL-2", branch=self.b_osh)
        row2 = kargo_push.sale_row(Sale.objects.select_related("account", "branch", "warehouse_item__order").get(pk=s2.pk), {"Ош": 2}, 5)
        self.assertEqual(row2["fk_i_admin_id"], 2)

    def test_imported_from_kargo_never_pushed(self):
        s = Sale.objects.create(client_code="AL-1", amount_mode="DIRECT", account=self.acc, price_som=Decimal("10"),
                                date=date(2026, 9, 1), legacy_kargo_id=555)
        s = Sale.objects.get(pk=s.pk)
        self.assertFalse(s.kargo_sync_pending)
        self.assertIsNone(kargo_push.sale_row(s, {}, 2))

    def test_direct_sale_is_delivered(self):
        s = Sale.objects.create(client_code="al-12345", amount_mode="DIRECT", account=self.acc, price_som=Decimal("300"),
                                weight_kg=Decimal("1"), date=date(2026, 9, 1), branch=self.b_osh)
        row = kargo_push.sale_row(Sale.objects.select_related("account", "branch").get(pk=s.pk), {"Ош": 2}, 2)
        self.assertEqual((row["i_status"], row["s_user_code"]), (3, "AL-12345"))

    def test_business_sale_ignored(self):
        biz = Account.objects.create(name="Биз", kind="BANK", currency="KGS", module="BUSINESS")
        s = Sale.objects.create(client_code="X", amount_mode="DIRECT", account=biz, price_som=Decimal("1"), date=date(2026, 9, 1))
        self.assertFalse(Sale.objects.get(pk=s.pk).kargo_sync_pending)


@override_settings(KARGO_DB_HOST="fake", KARGO_PUSH_IMMEDIATE=False, KARGO_DEFAULT_ADMIN_ID=2)
class PushTests(Base):
    def test_push_inserts_then_updates(self):
        o, it, s = self._received(track="TRK-100")
        cur = FakeCursor()
        stats = kargo_push.push_pending(conn=FakeConn(cur))
        self.assertEqual(stats["inserted"], 1)
        s.refresh_from_db()
        self.assertEqual((s.legacy_kargo_id, s.kargo_sync_pending), (900001, False))
        self.assertIsNotNone(s.kargo_pushed_at)
        insert = [q for q, _ in cur.sql if q.startswith("INSERT")][0]
        self.assertIn("s_tracking_number", insert)
        # выдача → UPDATE той же строки со статусом 3
        o.status = WarehouseOrder.Status.ISSUED
        o.save()
        cur2 = FakeCursor()
        stats = kargo_push.push_pending(conn=FakeConn(cur2))
        self.assertEqual(stats["updated"], 1)
        upd = [(q, p) for q, p in cur2.sql if q.startswith("UPDATE")][0]
        self.assertEqual(upd[1][-1], 900001)
        self.assertIn(3, upd[1])

    def test_existing_track_in_kargo_is_updated_not_duplicated(self):
        o, it, s = self._received(track="DUP-1")
        cur = FakeCursor(existing_track="DUP-1")
        stats = kargo_push.push_pending(conn=FakeConn(cur))
        self.assertEqual((stats["inserted"], stats["updated"]), (0, 1))
        s.refresh_from_db()
        self.assertEqual(s.legacy_kargo_id, 777)

    def test_unreachable_mysql_keeps_pending(self):
        o, it, s = self._received()
        with mock.patch.object(kargo_push, "connect", side_effect=OSError("down")):
            stats = kargo_push.push_pending()
        self.assertIn("error", stats)
        self.assertTrue(Sale.objects.get(pk=s.pk).kargo_sync_pending)

    def test_receive_api_accepts_tracking_and_rejects_duplicate(self):
        Sale.objects.create(client_code="Q", amount_mode="DIRECT", account=self.acc, price_som=Decimal("1"), date=date(2026, 9, 1), tracking_number="TAKEN")
        o = WarehouseOrder.objects.create(branch=self.b_loko, created_by=self.op, client_codes=["AL-12345"])
        it = WarehouseItem.objects.create(order=o, client_code="AL-12345")
        self.client.force_authenticate(self.wh)
        self.client.post(f"/api/warehouse-items/{it.id}/locate/")
        self.client.force_authenticate(self.op)
        r = self.client.post(f"/api/warehouse-items/{it.id}/receive/", {"weight_kg": "1", "account": self.acc.id, "tracking_number": "TAKEN"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f"/api/warehouse-items/{it.id}/receive/", {"weight_kg": "1", "account": self.acc.id, "tracking_number": " NEW-1 "}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Sale.objects.get(pk=it.sale_id if False else WarehouseItem.objects.get(pk=it.id).sale_id).tracking_number, "NEW-1")
