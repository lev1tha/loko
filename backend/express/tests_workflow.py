"""Тесты «процесса работы» для директора и остатка веса на складе."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from express.models import Sale, WarehouseItem, WarehouseOrder, WarehouseStock
from finance.models import Account, AppSettings, Branch

User = get_user_model()


def _settings():
    cfg = AppSettings.load()
    cfg.price_per_kg_usd = Decimal("3")
    cfg.usd_rate_som = Decimal("90")
    cfg.base_cost_per_kg_som = Decimal("100")
    cfg.save()


class Base(APITestCase):
    def setUp(self):
        _settings()
        self.acc = Account.objects.create(name="Нал", kind="CASH", currency="KGS", module="EXPRESS")
        self.b1 = Branch.objects.create(name="Филиал 1", is_default=True)
        self.b2 = Branch.objects.create(name="Филиал 2")
        self.admin = User.objects.create_user("adm", password="pass1234", role=User.Role.ADMIN)
        self.dir_ex = User.objects.create_user("dir_ex", password="pass1234", role=User.Role.DIRECTOR, module="EXPRESS")
        self.dir_bz = User.objects.create_user("dir_bz", password="pass1234", role=User.Role.DIRECTOR, module="BUSINESS")
        self.op = User.objects.create_user("op", password="pass1234", role=User.Role.OPERATOR, branch=self.b1, first_name="Оператор", last_name="Один")
        self.wh = User.objects.create_user("wh", password="pass1234", role=User.Role.WAREHOUSE, branch=self.b1, first_name="Склад", last_name="Иванов")

    def as_(self, user):
        self.client.force_authenticate(user)

    def _order(self, codes, branch=None, by=None):
        o = WarehouseOrder.objects.create(branch=branch or self.b1, created_by=by or self.op, client_codes=codes)
        return o, [WarehouseItem.objects.create(order=o, client_code=c) for c in codes]


class WorkflowAccessTests(Base):
    def test_roles(self):
        # директор любого направления видит процесс (директор видит оба направления)
        for user, code in ((self.admin, 200), (self.dir_ex, 200), (self.dir_bz, 200), (self.op, 403), (self.wh, 403)):
            self.as_(user)
            self.assertEqual(self.client.get("/api/reports/workflow/").status_code, code, user.username)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/reports/workflow/").status_code, 401)

    def test_director_still_blocked_from_warehouse_module(self):
        self.as_(self.dir_ex)
        self.assertEqual(self.client.get("/api/warehouse-orders/").status_code, 403)
        self.assertEqual(self.client.get("/api/warehouse-items/").status_code, 403)


class WorkflowContentTests(Base):
    def test_employees_active_and_evening(self):
        o1, (a, b, c) = self._order(["A1", "A2", "A3"])
        o2, (d,) = self._order(["B1"], branch=self.b2)
        a.receive("2", self.acc, by_user=self.wh)          # 2 кг × 270 = 540
        b.mark_not_found("нет на полке", by_user=self.wh)
        b.send_to_evening()
        # c остаётся в поиске; d — в поиске в другом филиале

        self.as_(self.dir_ex)
        r = self.client.get("/api/reports/workflow/")
        self.assertEqual(r.status_code, 200)
        t = r.data["totals"]
        self.assertEqual((t["orders_created"], t["items_created"], t["items_found"], t["kg_found"], t["som_found"]),
                         (2, 4, 1, "2.000", "540.00"))
        self.assertEqual((t["in_search_now"], t["active_orders_now"], t["evening_now"], t["items_not_found"]), (2, 2, 1, 0))
        by = {e["username"]: e for e in r.data["employees"]}
        self.assertEqual((by["op"]["orders_created"], by["op"]["items_created"]), (2, 4))
        self.assertEqual((by["wh"]["items_found"], by["wh"]["kg_found"], by["wh"]["som_found"], by["wh"]["items_evening"]),
                         (1, "2.000", "540.00", 1))
        self.assertEqual(by["wh"]["name"], "Склад Иванов")
        self.assertEqual({o["id"] for o in r.data["active_orders"]}, {o1.id, o2.id})
        self.assertEqual([e["client_code"] for e in r.data["evening"]], ["A2"])
        self.assertEqual(r.data["evening"][0]["reason"], "нет на полке")

        # фильтр по филиалу
        r = self.client.get("/api/reports/workflow/", {"branch": self.b2.id})
        self.assertEqual((r.data["totals"]["active_orders_now"], r.data["totals"]["evening_now"]), (1, 0))
        self.assertEqual([o["id"] for o in r.data["active_orders"]], [o2.id])

    def test_period_excludes_old(self):
        o, (a,) = self._order(["Z1"])
        a.receive("1", self.acc, by_user=self.wh)
        self.as_(self.admin)
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        r = self.client.get("/api/reports/workflow/", {"from": yesterday, "to": yesterday})
        self.assertEqual((r.data["totals"]["items_found"], r.data["employees"]), (0, []))
        self.assertEqual(r.data["totals"]["in_search_now"], 0)  # но «сейчас» — без периода
        r = self.client.get("/api/reports/workflow/", {"from": "bad"})
        self.assertEqual(r.status_code, 400)


class StockTests(Base):
    def _sale(self, kg, branch=None, d=None, **kw):
        kw.setdefault("amount_mode", "WEIGHT")
        return Sale.objects.create(client_code="X", weight_kg=Decimal(kg), account=self.acc,
                                   branch=branch or self.b1, date=d or timezone.localdate(), **kw)

    def test_access(self):
        for user, code in ((self.dir_ex, 200), (self.admin, 200), (self.dir_bz, 200), (self.op, 403), (self.wh, 200)):
            self.as_(user)
            self.assertEqual(self.client.get("/api/warehouse-stock/summary/", {"branch": self.b1.id}).status_code, code, user.username)

    def test_warehouse_sees_only_own_branch_summary(self):
        WarehouseStock.objects.create(branch=self.b2, date=timezone.localdate(), kg=Decimal("50"))
        self.as_(self.wh)  # филиал b1
        r = self.client.get("/api/warehouse-stock/summary/", {"branch": self.b2.id})
        self.assertEqual((r.status_code, r.data["branch"], r.data["balance_kg"]), (200, self.b1.id, "0.000"))
        self.assertEqual(self.client.get("/api/warehouse-stock/").status_code, 403)
        self.assertEqual(self.client.post("/api/warehouse-stock/", {"branch": self.b1.id, "date": str(timezone.localdate()), "kg": "1"}, format="json").status_code, 403)
        self.wh.branch = None
        self.wh.save()
        self.assertEqual(self.client.get("/api/warehouse-stock/summary/").status_code, 400)

    def test_balance_carries_over(self):
        today = timezone.localdate()
        yday = today - timedelta(days=1)
        self.as_(self.dir_ex)
        r = self.client.post("/api/warehouse-stock/", {"branch": self.b1.id, "date": yday.isoformat(), "kg": "200"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["created_by_name"], "dir_ex")
        # вчера сотрудники оприходовали 160 кг (склад + прямая продажа кассира)
        o, (it,) = self._order(["C1"])
        s = it.receive("100", self.acc, by_user=self.wh)
        Sale.objects.filter(pk=s.pk).update(date=yday)
        self._sale("60", d=yday)
        # чужой филиал, Kargo-история и Kargo-цикл — не расход этого склада
        self._sale("500", branch=self.b2, d=yday)
        self._sale("500", d=yday, legacy_kargo_id=1)
        self._sale("500", d=yday, delivery_status="ARRIVED", amount_mode="DIRECT", price_som=Decimal("0"))

        r = self.client.get("/api/warehouse-stock/summary/", {"branch": self.b1.id})
        self.assertEqual(r.data["balance_kg"], "40.000")
        self.assertEqual((r.data["added_kg"], r.data["consumed_kg"], r.data["since"]), ("200.000", "160.000", yday.isoformat()))

        # сегодня пришло ещё 150 → 190; продано 10 → 180
        self.client.post("/api/warehouse-stock/", {"branch": self.b1.id, "date": today.isoformat(), "kg": "150", "note": "фура"}, format="json")
        self._sale("10")
        r = self.client.get("/api/warehouse-stock/summary/", {"branch": self.b1.id})
        self.assertEqual(r.data["balance_kg"], "180.000")
        days = {d["date"]: d for d in r.data["days"]}
        self.assertEqual((days[yday.isoformat()]["balance_kg"], days[today.isoformat()]["added_kg"], days[today.isoformat()]["consumed_kg"]),
                         ("40.000", "150.000", "10.000"))
        self.assertEqual(r.data["days"][0]["date"], today.isoformat())  # свежие сверху
        self.assertEqual(len(r.data["entries"]), 2)

        # корректировка до фактического остатка: −5 → 175
        r = self.client.post("/api/warehouse-stock/", {"branch": self.b1.id, "date": today.isoformat(), "kind": "ADJUST", "kg": "-5", "note": "пересчёт"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        r = self.client.get("/api/warehouse-stock/summary/", {"branch": self.b1.id})
        self.assertEqual(r.data["balance_kg"], "175.000")

    def test_validation_and_delete_rules(self):
        self.as_(self.dir_ex)
        today = timezone.localdate().isoformat()
        self.assertEqual(self.client.post("/api/warehouse-stock/", {"branch": self.b1.id, "date": today, "kg": "0"}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/warehouse-stock/", {"branch": self.b1.id, "date": today, "kind": "ADJUST", "kg": "0"}, format="json").status_code, 400)
        r = self.client.post("/api/warehouse-stock/", {"branch": self.b1.id, "date": today, "kg": "5"}, format="json")
        eid = r.data["id"]
        # PATCH запрещён (только создание/удаление)
        self.assertEqual(self.client.patch(f"/api/warehouse-stock/{eid}/", {"kg": "6"}, format="json").status_code, 405)
        # чужой (не админ) удалить не может
        other = User.objects.create_user("dir2", password="pass1234", role=User.Role.DIRECTOR, module="EXPRESS")
        self.as_(other)
        self.assertEqual(self.client.delete(f"/api/warehouse-stock/{eid}/").status_code, 400)
        self.as_(self.admin)
        self.assertEqual(self.client.delete(f"/api/warehouse-stock/{eid}/").status_code, 204)
        self.assertEqual(WarehouseStock.objects.count(), 0)

    def test_summary_default_branch_and_empty(self):
        self.as_(self.dir_ex)
        r = self.client.get("/api/warehouse-stock/summary/")
        self.assertEqual((r.status_code, r.data["branch"], r.data["balance_kg"], r.data["days"]), (200, self.b1.id, "0.000", []))
        r = self.client.get("/api/warehouse-stock/branches/")
        names = [b["name"] for b in r.data]  # плюс филиалы из seed-миграции
        self.assertTrue({"Филиал 1", "Филиал 2"} <= set(names))
