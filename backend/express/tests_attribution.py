"""Заявка клиента (QR) закрепляется за сотрудником филиала; период в «Моих продажах»."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APITestCase

from express.models import Sale, WarehouseItem, WarehouseOrder
from finance.models import Account, AppSettings, Branch

User = get_user_model()


class Base(APITestCase):
    def setUp(self):
        cache.clear()  # лимит публичной самозаписи (throttle) живёт в кеше между тестами
        cfg = AppSettings.load(); cfg.price_per_kg_usd = Decimal("3"); cfg.usd_rate_som = Decimal("90"); cfg.save()
        self.acc = Account.objects.create(name="Нал", kind="CASH", currency="KGS", module="EXPRESS")
        self.b1 = Branch.objects.create(name="Точка 1", is_default=True)
        self.b2 = Branch.objects.create(name="Точка 2")
        self.op1 = User.objects.create_user("op1", password="x", role=User.Role.OPERATOR, branch=self.b1, first_name="Алмаз")
        self.op2 = User.objects.create_user("op2", password="x", role=User.Role.OPERATOR, branch=self.b2)
        self.wh1 = User.objects.create_user("wh1", password="x", role=User.Role.WAREHOUSE, branch=self.b1)
        self.admin = User.objects.create_user("adm", password="x", role=User.Role.ADMIN)

    def intake(self, branch, phone="996700111222", codes=("Q1",)):
        r = self.client.post("/api/public/intake/", {"branch": branch.id, "phone": phone, "name": "Клиент", "client_codes": list(codes)}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return WarehouseOrder.objects.latest("id")


class IntakeAttributionTests(Base):
    def test_single_operator_branch_autoassigns_and_operator_sees_it(self):
        o = self.intake(self.b1)
        self.assertEqual(o.created_by, self.op1)
        self.client.force_authenticate(self.op1)
        r = self.client.get("/api/warehouse-items/mine/")
        self.assertEqual([i["client_code"] for i in r.data["results"]], ["Q1"])
        self.assertEqual(r.data["results"][0]["status"], "IN_SEARCH")

    def test_multiple_operators_leave_unassigned(self):
        User.objects.create_user("op1b", password="x", role=User.Role.OPERATOR, branch=self.b1)
        o = self.intake(self.b1)
        self.assertIsNone(o.created_by)

    def test_no_operators_leave_unassigned(self):
        self.op2.delete()
        o = self.intake(self.b2)
        self.assertIsNone(o.created_by)


class ReceiveAttributionTests(Base):
    def _unassigned(self):
        User.objects.create_user("op1b", password="x", role=User.Role.OPERATOR, branch=self.b1, first_name="Бек")
        o = self.intake(self.b1)
        return o, o.items.first()

    def test_receive_requires_operator_when_ambiguous(self):
        o, it = self._unassigned()
        self.client.force_authenticate(self.admin)
        r = self.client.post(f"/api/warehouse-items/{it.id}/receive/", {"weight_kg": "1", "account": self.acc.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("operator", r.data)

    def test_receive_with_operator_assigns_and_attributes_sale(self):
        o, it = self._unassigned()
        self.client.force_authenticate(self.admin)
        r = self.client.post(f"/api/warehouse-items/{it.id}/receive/", {"weight_kg": "2", "account": self.acc.id, "operator": self.op1.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        o.refresh_from_db(); it.refresh_from_db()
        self.assertEqual(o.created_by, self.op1)
        self.assertEqual(it.sale.created_by, self.op1)
        self.assertEqual(it.sale.price_som, Decimal("540.00"))
        # сотрудник видит позицию с ценой
        self.client.force_authenticate(self.op1)
        r = self.client.get("/api/warehouse-items/mine/")
        self.assertEqual((r.data["results"][0]["status"], r.data["results"][0]["price_som"]), ("FOUND", "540.00"))

    def test_receive_rejects_operator_from_other_branch(self):
        o, it = self._unassigned()
        self.client.force_authenticate(self.admin)
        r = self.client.post(f"/api/warehouse-items/{it.id}/receive/", {"weight_kg": "1", "account": self.acc.id, "operator": self.op2.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("operator", r.data)

    def test_receive_autoassigns_single_operator_without_param(self):
        # заявка создана до появления сотрудника → при приёме закрепится автоматически
        self.op1.delete()
        o = self.intake(self.b1)
        self.assertIsNone(o.created_by)
        op = User.objects.create_user("late", password="x", role=User.Role.OPERATOR, branch=self.b1)
        self.client.force_authenticate(self.admin)
        r = self.client.post(f"/api/warehouse-items/{o.items.first().id}/receive/", {"weight_kg": "1", "account": self.acc.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        o.refresh_from_db(); self.assertEqual(o.created_by, op)

    def test_operator_receives_located_and_takes_unassigned_order(self):
        o, it = self._unassigned()                       # заявка клиента, сотрудников на точке два
        self.client.force_authenticate(self.op1)
        r = self.client.post(f"/api/warehouse-items/{it.id}/receive/", {"weight_kg": "1", "account": self.acc.id}, format="json")
        self.assertEqual(r.status_code, 400)             # склад ещё не отметил «найдено»
        self.client.force_authenticate(self.wh1)
        r = self.client.post(f"/api/warehouse-items/{it.id}/locate/")
        self.assertEqual((r.status_code, r.data["status"], r.data["found_by_name"]), (200, "LOCATED", "wh1"))
        self.assertEqual(self.client.post(f"/api/warehouse-items/{it.id}/receive/", {"weight_kg": "1", "account": self.acc.id}, format="json").status_code, 403)
        self.client.force_authenticate(self.op1)
        r = self.client.post(f"/api/warehouse-items/{it.id}/receive/", {"weight_kg": "2", "account": self.acc.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        o.refresh_from_db(); it.refresh_from_db()
        self.assertEqual((o.created_by, it.found_by, it.received_by, it.sale.created_by), (self.op1, self.wh1, self.op1, self.op1))

    def test_operators_picker(self):
        User.objects.create_user("op1b", password="x", role=User.Role.OPERATOR, branch=self.b1, first_name="Бек")
        self.client.force_authenticate(self.wh1)
        r = self.client.get("/api/warehouse-items/operators/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([o["name"] for o in r.data], ["Алмаз", "Бек"])
        self.client.force_authenticate(self.admin)
        r = self.client.get("/api/warehouse-items/operators/", {"branch": self.b2.id})
        self.assertEqual([o["name"] for o in r.data], ["op2"])
        self.client.force_authenticate(self.op1)
        self.assertEqual(self.client.get("/api/warehouse-items/operators/").status_code, 403)


class MinePeriodTests(Base):
    def test_period_filters(self):
        o = WarehouseOrder.objects.create(branch=self.b1, created_by=self.op1, client_codes=["OLD", "NEW"])
        old = WarehouseItem.objects.create(order=o, client_code="OLD")
        WarehouseItem.objects.create(order=o, client_code="NEW")
        month_start = timezone.localtime(timezone.now()).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        WarehouseItem.objects.filter(pk=old.pk).update(created_at=month_start - timedelta(days=3))
        self.client.force_authenticate(self.op1)
        codes = lambda r: sorted(i["client_code"] for i in r.data["results"])
        self.assertEqual(codes(self.client.get("/api/warehouse-items/mine/")), ["NEW"])
        self.assertEqual(codes(self.client.get("/api/warehouse-items/mine/", {"period": "prev"})), ["OLD"])
        self.assertEqual(codes(self.client.get("/api/warehouse-items/mine/", {"period": "all"})), ["NEW", "OLD"])


class AssignCommandTests(Base):
    def _client_order(self, branch, code, receive=False):
        o = WarehouseOrder.objects.create(branch=branch, client_codes=[code])
        it = WarehouseItem.objects.create(order=o, client_code=code)
        if receive:
            it.receive("1", self.acc, by_user=self.wh1)
        return o, it

    def test_assigns_single_operator_branches_and_their_sales(self):
        from io import StringIO
        from django.core.management import call_command
        o1, it1 = self._client_order(self.b1, "A1", receive=True)
        o2, it2 = self._client_order(self.b1, "A2")
        Sale.objects.filter(pk=it1.sale_id).update(created_by=None)
        out = StringIO()
        call_command("assign_client_orders", "--dry-run", stdout=out)
        o1.refresh_from_db(); self.assertIsNone(o1.created_by)          # dry-run ничего не пишет
        call_command("assign_client_orders", stdout=out)
        o1.refresh_from_db(); o2.refresh_from_db()
        self.assertEqual((o1.created_by, o2.created_by), (self.op1, self.op1))
        self.assertEqual(Sale.objects.get(pk=it1.sale_id).created_by, self.op1)
        self.assertIn("Закреплено заявок: 2, продаж: 1", out.getvalue())

    def test_ambiguous_branch_skipped_unless_forced(self):
        from io import StringIO
        from django.core.management import call_command
        User.objects.create_user("op1b", password="x", role=User.Role.OPERATOR, branch=self.b1)
        o, it = self._client_order(self.b1, "B1")
        out = StringIO()
        call_command("assign_client_orders", stdout=out)
        o.refresh_from_db(); self.assertIsNone(o.created_by)
        self.assertIn("пропущено", out.getvalue())
        call_command("assign_client_orders", "--branch", str(self.b1.id), "--operator", "op1b", stdout=out)
        o.refresh_from_db(); self.assertEqual(o.created_by.username, "op1b")
        with self.assertRaises(Exception):
            call_command("assign_client_orders", "--branch", str(self.b1.id), "--operator", "op2", stdout=out)  # другой филиал
