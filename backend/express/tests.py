from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from finance.models import Account, AppSettings, Branch
from express.models import Client, ClientPrice, EmployeeRating, Sale, WarehouseOrder

User = get_user_model()


def _settings():
    cfg = AppSettings.load()
    cfg.price_per_kg_usd = Decimal("3")
    cfg.usd_rate_som = Decimal("90")  # 3$ × 90 = 270 сом/кг
    cfg.base_cost_per_kg_som = Decimal("100")
    cfg.save()
    return cfg


class EstWeightTests(APITestCase):
    """Расчётный («предположительный») вес для показа админу."""

    def setUp(self):
        _settings()
        self.acc = Account.objects.create(name="Нал", kind="CASH", currency="KGS", module="EXPRESS")

    def test_direct_sale_derives_weight_from_sum(self):
        # 27000 сом ÷ 270 сом/кг = 100.00 кг
        s = Sale.objects.create(
            client_code="A", amount_mode="DIRECT", price_som=Decimal("27000"),
            account=self.acc, date="2026-06-01",
        )
        self.assertIsNone(s.weight_kg)
        self.assertEqual(s.est_weight_kg, Decimal("100.00"))

    def test_weight_sale_rounds_to_two_decimals(self):
        s = Sale.objects.create(
            client_code="B", amount_mode="WEIGHT", weight_kg=Decimal("2.5"),
            account=self.acc, date="2026-06-01",
        )
        self.assertEqual(s.est_weight_kg, Decimal("2.50"))

    def test_serializer_exposes_est_weight(self):
        admin = User.objects.create_user("admin1", password="pass1234", role=User.Role.ADMIN)
        self.client.force_authenticate(admin)
        Sale.objects.create(
            client_code="C", amount_mode="DIRECT", price_som=Decimal("13500"),
            account=self.acc, date="2026-06-01",
        )
        r = self.client.get("/api/sales/", {"page_size": 100})
        self.assertEqual(r.status_code, 200)
        results = r.data.get("results", r.data)
        self.assertTrue(any(row.get("est_weight_kg") == "50.00" for row in results))


class ClientPriceTests(APITestCase):
    """Индивидуальная цена за кг по клиенту + upsert по коду."""

    def setUp(self):
        _settings()
        self.admin = User.objects.create_user("admin2", password="pass1234", role=User.Role.ADMIN)
        self.client.force_authenticate(self.admin)

    def test_upsert_does_not_duplicate(self):
        r1 = self.client.post("/api/client-prices/", {"client_code": "29520", "price_per_kg_som": "250"}, format="json")
        self.assertIn(r1.status_code, (200, 201))
        r2 = self.client.post("/api/client-prices/", {"client_code": "29520", "price_per_kg_som": "220"}, format="json")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(ClientPrice.objects.filter(client_code="29520").count(), 1)
        self.assertEqual(ClientPrice.objects.get(client_code="29520").price_per_kg_som, Decimal("220"))

    def test_lookup_by_client_code(self):
        ClientPrice.objects.create(client_code="31044", price_per_kg_som=Decimal("220"))
        r = self.client.get("/api/client-prices/", {"client_code": "31044"})
        self.assertEqual(r.status_code, 200)
        results = r.data.get("results", r.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["price_per_kg_som"], "220.00")

    def test_rejects_nonpositive_price(self):
        r = self.client.post("/api/client-prices/", {"client_code": "x", "price_per_kg_som": "0"}, format="json")
        self.assertEqual(r.status_code, 400)


class WeightClientPriceTests(APITestCase):
    """Спец-цена клиента авто-применяется в режиме «по весу» (в т.ч. у сотрудника)."""

    def setUp(self):
        _settings()  # цена по умолчанию 3$ × 90 = 270 сом/кг
        self.acc = Account.objects.create(name="Нал-вес", kind="CASH", currency="KGS", module="EXPRESS")
        ClientPrice.objects.create(client_code="VIP", price_per_kg_som=Decimal("250"))

    def test_weight_sale_uses_client_price(self):
        s = Sale.objects.create(
            client_code="VIP", amount_mode="WEIGHT", weight_kg=Decimal("4"),
            account=self.acc, date="2026-06-01",
        )
        self.assertEqual(s.price_som, Decimal("1000.00"))  # 4 × 250

    def test_weight_sale_default_without_client_price(self):
        s = Sale.objects.create(
            client_code="REG", amount_mode="WEIGHT", weight_kg=Decimal("4"),
            account=self.acc, date="2026-06-01",
        )
        self.assertEqual(s.price_som, Decimal("1080.00"))  # 4 × 270

    def test_quote_applies_client_price(self):
        # Quote — теперь только кассир/админ (оператор со SaleViewSet снят).
        mgr = User.objects.create_user("mgr_q", password="pass1234", role=User.Role.MANAGER)
        self.client.force_authenticate(mgr)
        r = self.client.post("/api/sales/quote/", {"weight_kg": "4", "client_code": "VIP"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["price_som"], Decimal("1000.00"))  # 4 × 250 (спец-цена)


class OperatorRequestTests(APITestCase):
    """Двухэтапный учёт: оператор создаёт СКЛАДСКУЮ ЗАЯВКУ с кодами — БЕЗ продажи.

    Продажа (Sale) рождается только при оприходовании складом (см. TwoStageFlowTests).
    """

    def setUp(self):
        self.default_branch = Branch.objects.create(name="Гульчинская", is_default=True)
        self.staff_branch = Branch.objects.create(name="Раззакова", is_default=False)

    def test_operator_cannot_create_direct_sale(self):
        # Оператор снят со SaleViewSet — прямой продажи он больше не создаёт.
        acc = Account.objects.create(name="Нал", kind="CASH", currency="KGS", module="EXPRESS")
        op = User.objects.create_user("op_x", password="p", role=User.Role.OPERATOR, branch=self.staff_branch)
        self.client.force_authenticate(op)
        r = self.client.post("/api/sales/", {
            "amount_mode": "DIRECT", "client_code": "A1", "price_som": "5000",
            "account": acc.id, "date": "2026-06-01",
        }, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Sale.objects.exists())

    def test_operator_request_creates_items_no_sale(self):
        op = User.objects.create_user("op_r", password="p", role=User.Role.OPERATOR, branch=self.staff_branch)
        self.client.force_authenticate(op)
        r = self.client.post("/api/warehouse-orders/", {"client_codes": ["A1", "A2", "A3"]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        order = WarehouseOrder.objects.get()
        self.assertEqual(order.branch_id, self.staff_branch.id)  # филиал сотрудника
        items = list(order.items.all())
        self.assertEqual(len(items), 3)
        # Все позиции «в поиске», продаж нет.
        self.assertTrue(all(i.status == "IN_SEARCH" for i in items))
        self.assertTrue(all(i.sale_id is None for i in items))
        self.assertFalse(Sale.objects.exists())

    def test_operator_without_branch_blocked(self):
        op = User.objects.create_user("op_nb", password="p", role=User.Role.OPERATOR)
        self.client.force_authenticate(op)
        r = self.client.post("/api/warehouse-orders/", {"client_codes": ["B1"]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("branch", r.data)
        self.assertFalse(WarehouseOrder.objects.exists())


class WarehouseBranchScopeTests(APITestCase):
    """Складовщик видит и создаёт заявки ТОЛЬКО своего филиала (без филиала — ничего).

    Зеркало правил сотрудника: у обоих филиал — жёсткая привязка, без «дефолта».
    """

    def setUp(self):
        self.branch_a = Branch.objects.create(name="Филиал A", is_default=True)
        self.branch_b = Branch.objects.create(name="Филиал B", is_default=False)
        self.wh_a = User.objects.create_user(
            "wh_a", password="pass1234", role=User.Role.WAREHOUSE, branch=self.branch_a
        )
        # Заявки в обоих филиалах — складовщик A должен видеть только «свою».
        self.order_a = WarehouseOrder.objects.create(
            branch=self.branch_a, created_by=self.wh_a, client_codes=["AAA"],
            status=WarehouseOrder.Status.NEW,
        )
        self.order_b = WarehouseOrder.objects.create(
            branch=self.branch_b, created_by=self.wh_a, client_codes=["BBB"],
            status=WarehouseOrder.Status.NEW,
        )

    def _ids(self, resp):
        results = resp.data.get("results", resp.data)
        return {o["id"] for o in results}

    def test_warehouse_sees_only_own_branch(self):
        self.client.force_authenticate(self.wh_a)
        r = self.client.get("/api/warehouse-orders/")
        self.assertEqual(r.status_code, 200)
        ids = self._ids(r)
        self.assertIn(self.order_a.id, ids)
        self.assertNotIn(self.order_b.id, ids)  # чужой филиал не виден

    def test_warehouse_without_branch_sees_nothing(self):
        wh_none = User.objects.create_user("wh_none", password="pass1234", role=User.Role.WAREHOUSE)
        self.client.force_authenticate(wh_none)
        r = self.client.get("/api/warehouse-orders/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data.get("results", r.data)), 0)

    def test_warehouse_create_files_to_own_branch(self):
        self.client.force_authenticate(self.wh_a)
        r = self.client.post("/api/warehouse-orders/", {"client_codes": ["ZZZ"]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        # Филиал берётся с сервера (филиал складовщика), а не из тела запроса.
        self.assertEqual(r.data["branch"], self.branch_a.id)

    def test_warehouse_without_branch_cannot_create(self):
        wh_none = User.objects.create_user("wh_none2", password="pass1234", role=User.Role.WAREHOUSE)
        self.client.force_authenticate(wh_none)
        before = WarehouseOrder.objects.count()
        r = self.client.post("/api/warehouse-orders/", {"client_codes": ["QQQ"]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("branch", r.data)
        self.assertEqual(WarehouseOrder.objects.count(), before)  # ничего не создано


class WarehouseNotFoundTests(APITestCase):
    """Статус «Не найдено» — обратимое проблемное состояние (товара нет на складе)."""

    def setUp(self):
        self.branch = Branch.objects.create(name="Ф-НФ", is_default=True)
        self.wh = User.objects.create_user(
            "wh_nf", password="pass1234", role=User.Role.WAREHOUSE, branch=self.branch
        )
        self.order = WarehouseOrder.objects.create(
            branch=self.branch, created_by=self.wh, client_codes=["X1"],
            status=WarehouseOrder.Status.IN_PROGRESS,
        )
        self.client.force_authenticate(self.wh)

    def _set(self, status, comment=None):
        body = {"status": status}
        if comment is not None:
            body["comment"] = comment
        return self.client.post(f"/api/warehouse-orders/{self.order.id}/status/", body, format="json")

    def test_not_found_requires_reason(self):
        r = self._set("NOT_FOUND")
        self.assertEqual(r.status_code, 400)
        self.assertIn("comment", r.data)

    def test_mark_not_found_saves_reason(self):
        r = self._set("NOT_FOUND", "нет на стеллаже A")
        self.assertEqual(r.status_code, 200, r.data)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "NOT_FOUND")
        self.assertEqual(self.order.comment, "нет на стеллаже A")

    def test_not_found_reversible_back_to_search(self):
        self.order.status = WarehouseOrder.Status.NOT_FOUND
        self.order.save()
        r = self._set("IN_PROGRESS")  # нашёлся/приехал → снова в поиск
        self.assertEqual(r.status_code, 200, r.data)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "IN_PROGRESS")

    def test_not_found_cannot_jump_straight_to_ready(self):
        self.order.status = WarehouseOrder.Status.NOT_FOUND
        self.order.save()
        r = self._set("READY")  # только через «в поиск»
        self.assertEqual(r.status_code, 400)
        self.assertIn("status", r.data)


class TwoStageFlowTests(APITestCase):
    """Полный двухэтапный цикл: заявка оператора → пошту́чное оприходование склада.

    Проверяет ядро новой логики: продажа (и финансы) появляется ТОЛЬКО при FOUND;
    NOT_FOUND продажи не создаёт; крестик оператора уводит позицию в вечерний
    допоиск; складовщик видит вечерний список; «мои» позиции показывают статусы.
    """

    def setUp(self):
        _settings()  # 3$ × 90 = 270 сом/кг
        self.acc = Account.objects.create(name="Касса", kind="CASH", currency="KGS", module="EXPRESS")
        self.branch = Branch.objects.create(name="Ф2", is_default=True)
        self.op = User.objects.create_user("op2", password="p", role=User.Role.OPERATOR, branch=self.branch)
        self.wh = User.objects.create_user("wh2", password="p", role=User.Role.WAREHOUSE, branch=self.branch)

    def _make_order(self, codes):
        self.client.force_authenticate(self.op)
        r = self.client.post("/api/warehouse-orders/", {"client_codes": codes}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return WarehouseOrder.objects.get()

    def test_receive_creates_sale_only_on_found(self):
        order = self._make_order(["F1", "N1"])
        found_item, nf_item = order.items.order_by("id")
        self.client.force_authenticate(self.wh)

        # FOUND: вес 3 кг → продажа по тарифу (3 × 270 = 810), финансы видят её.
        r = self.client.post(f"/api/warehouse-items/{found_item.id}/receive/",
                             {"weight_kg": "3", "account": self.acc.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        found_item.refresh_from_db()
        self.assertEqual(found_item.status, "FOUND")
        self.assertIsNotNone(found_item.sale_id)
        self.assertEqual(found_item.sale.price_som, Decimal("810.00"))
        self.assertEqual(found_item.sale.branch_id, self.branch.id)

        # NOT_FOUND: причина, продажа НЕ создаётся.
        r = self.client.post(f"/api/warehouse-items/{nf_item.id}/not-found/",
                             {"reason": "нет на складе"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        nf_item.refresh_from_db()
        self.assertEqual(nf_item.status, "NOT_FOUND")
        self.assertIsNone(nf_item.sale_id)

        # Финансы: ровно одна продажа — только оприходованная позиция.
        self.assertEqual(Sale.objects.count(), 1)

    def test_not_found_requires_reason(self):
        order = self._make_order(["Z1"])
        item = order.items.get()
        self.client.force_authenticate(self.wh)
        r = self.client.post(f"/api/warehouse-items/{item.id}/not-found/", {"reason": ""}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_operator_dismiss_moves_to_evening_and_warehouse_sees_it(self):
        order = self._make_order(["E1"])
        item = order.items.get()
        # Склад не нашёл.
        self.client.force_authenticate(self.wh)
        self.client.post(f"/api/warehouse-items/{item.id}/not-found/", {"reason": "нет"}, format="json")

        # Оператор жмёт крестик → вечерний допоиск.
        self.client.force_authenticate(self.op)
        r = self.client.post(f"/api/warehouse-items/{item.id}/to-evening/", format="json")
        self.assertEqual(r.status_code, 200, r.data)
        item.refresh_from_db()
        self.assertEqual(item.status, "EVENING")

        # Складовщик видит его в вечернем списке (фильтр status=EVENING).
        self.client.force_authenticate(self.wh)
        r = self.client.get("/api/warehouse-items/", {"status": "EVENING"})
        self.assertEqual(r.status_code, 200)
        codes = [x["client_code"] for x in r.data.get("results", r.data)]
        self.assertIn("E1", codes)

    def test_operator_cannot_dismiss_found_item(self):
        order = self._make_order(["G1"])
        item = order.items.get()
        self.client.force_authenticate(self.wh)
        self.client.post(f"/api/warehouse-items/{item.id}/receive/",
                        {"weight_kg": "2", "account": self.acc.id}, format="json")
        # Крестик разрешён только для NOT_FOUND — на найденной позиции 400.
        self.client.force_authenticate(self.op)
        r = self.client.post(f"/api/warehouse-items/{item.id}/to-evening/", format="json")
        self.assertEqual(r.status_code, 400)

    def test_operator_mine_shows_per_code_status(self):
        order = self._make_order(["M1", "M2"])
        found, nf = order.items.order_by("id")
        self.client.force_authenticate(self.wh)
        self.client.post(f"/api/warehouse-items/{found.id}/receive/",
                        {"weight_kg": "3", "account": self.acc.id}, format="json")
        self.client.post(f"/api/warehouse-items/{nf.id}/not-found/", {"reason": "нет"}, format="json")

        self.client.force_authenticate(self.op)
        r = self.client.get("/api/warehouse-items/mine/")
        self.assertEqual(r.status_code, 200)
        rows = {x["client_code"]: x for x in r.data["results"]}
        self.assertEqual(rows["M1"]["status"], "FOUND")
        self.assertEqual(rows["M1"]["price_som"], "810.00")   # видит сумму найденного
        self.assertEqual(rows["M2"]["status"], "NOT_FOUND")
        self.assertIsNone(rows["M2"]["price_som"])            # у не найденного суммы нет

    def test_operator_sees_only_own_items(self):
        self._make_order(["OWN"])
        other = User.objects.create_user("op_other", password="p", role=User.Role.OPERATOR, branch=self.branch)
        self.client.force_authenticate(other)
        r = self.client.get("/api/warehouse-items/mine/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 0)  # чужие позиции не видит


class ClientRegistrationTests(APITestCase):
    """Регистрация клиента по телефону (QR, публично), трекинг и CRM."""

    def setUp(self):
        self.branch = Branch.objects.create(name="Ф-CRM", is_default=True)

    def _intake(self, phone, codes, name=""):
        return self.client.post("/api/public/intake/", {
            "branch": self.branch.id, "phone": phone, "name": name, "client_codes": codes,
        }, format="json")

    def test_public_intake_registers_and_creates_items_no_sale(self):
        r = self._intake("+996 700 12-34-56", ["A1", "A2"], name="Азамат")  # анонимно
        self.assertEqual(r.status_code, 201, r.data)
        client = Client.objects.get()
        self.assertEqual(client.phone, "700123456")      # единый формат: 9 цифр без «996»
        self.assertEqual(client.name, "Азамат")
        order = WarehouseOrder.objects.get()
        self.assertEqual(order.client_id, client.id)
        self.assertIsNone(order.created_by_id)            # создал сам клиент
        self.assertEqual(order.items.count(), 2)
        self.assertTrue(all(i.status == "IN_SEARCH" for i in order.items.all()))
        self.assertFalse(Sale.objects.exists())           # продажи нет

    def test_same_phone_different_format_is_one_client(self):
        self._intake("+996 700 111 222", ["X1"])
        self._intake("0700111222", ["X2"])
        self._intake("700111222", ["X3"])
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(Client.objects.get(phone="700111222").orders.count(), 3)

    def test_public_track_by_phone(self):
        self._intake("996700999", ["T1"], name="Бек")
        r = self.client.get("/api/public/track/", {"phone": "+996 700 999"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["found"])
        self.assertEqual(r.data["client"]["name"], "Бек")
        self.assertIn("T1", [i["client_code"] for i in r.data["items"]])

    def test_track_unknown_phone(self):
        r = self.client.get("/api/public/track/", {"phone": "996000000"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["found"])

    def test_crm_access_and_stats(self):
        _settings()
        acc = Account.objects.create(name="K", kind="CASH", currency="KGS", module="EXPRESS")
        self._intake("996700555", ["F", "N"], name="Сеит")
        order = WarehouseOrder.objects.get()
        f = order.items.order_by("id").first()
        wh = User.objects.create_user("wh_crm", password="p", role=User.Role.WAREHOUSE, branch=self.branch)
        f.receive(Decimal("5"), acc, by_user=wh)          # FOUND: 5 кг × 270 = 1350

        # оператору CRM закрыт
        self.client.force_authenticate(User.objects.create_user("op_crm", password="p", role=User.Role.OPERATOR))
        self.assertEqual(self.client.get("/api/clients/").status_code, 403)

        # менеджер видит клиента с агрегатами (только оприходованное)
        self.client.force_authenticate(User.objects.create_user("mgr_crm", password="p", role=User.Role.MANAGER))
        r = self.client.get("/api/clients/")
        self.assertEqual(r.status_code, 200)
        row = next(c for c in r.data.get("results", r.data) if c["name"] == "Сеит")
        self.assertEqual(row["orders_count"], 1)
        self.assertEqual(row["total_kg"], "5.000")
        self.assertEqual(row["total_som"], "1350.00")


class AutoStarsTests(APITestCase):
    """Клиент оценивает сотрудника → средняя оценка авто-питает бонус «звёзды»."""

    def setUp(self):
        _settings()
        self.branch = Branch.objects.create(name="Ф-star", is_default=True)
        self.acc = Account.objects.create(name="K★", kind="CASH", currency="KGS", module="EXPRESS")
        self.wh = User.objects.create_user("wh_star", password="p", role=User.Role.WAREHOUSE, branch=self.branch)

    def _client_served(self, phone, name):
        # клиент по QR → склад оприходует один код (found_by = self.wh)
        self.client.post("/api/public/intake/", {
            "branch": self.branch.id, "phone": phone, "name": name, "client_codes": ["C1"],
        }, format="json")
        cl = Client.objects.get(phone=Client.normalize_phone(phone))
        WarehouseOrder.objects.get(client=cl).items.first().receive(Decimal("5"), self.acc, by_user=self.wh)
        return cl

    def test_track_lists_servant_staff(self):
        self._client_served("996700111", "А")
        r = self.client.get("/api/public/track/", {"phone": "996700111"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([s["id"] for s in r.data["staff"]], [self.wh.id])
        self.assertEqual(r.data["staff"][0]["my_stars"], 0)

    def test_rate_only_servant_and_upsert(self):
        self._client_served("996700222", "Б")
        r = self.client.post("/api/public/rate/", {"phone": "996700222", "employee": self.wh.id, "stars": 5}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(EmployeeRating.objects.get(employee=self.wh).stars, 5)
        # повторная оценка — обновление, не дубль
        self.client.post("/api/public/rate/", {"phone": "996700222", "employee": self.wh.id, "stars": 4}, format="json")
        self.assertEqual(EmployeeRating.objects.filter(employee=self.wh).count(), 1)
        self.assertEqual(EmployeeRating.objects.get(employee=self.wh).stars, 4)
        # нельзя оценить того, кто не обслуживал
        other = User.objects.create_user("wh_other", password="p", role=User.Role.WAREHOUSE, branch=self.branch)
        r = self.client.post("/api/public/rate/", {"phone": "996700222", "employee": other.id, "stars": 5}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_auto_stars_feed_bonus(self):
        from finance.bonuses import build_bonuses
        from django.utils import timezone
        self._client_served("996700333", "В")
        self._client_served("996700444", "Г")
        self.client.post("/api/public/rate/", {"phone": "996700333", "employee": self.wh.id, "stars": 5}, format="json")
        self.client.post("/api/public/rate/", {"phone": "996700444", "employee": self.wh.id, "stars": 4}, format="json")
        period = timezone.localdate().strftime("%Y-%m")
        row = next(r for r in build_bonuses(period) if r["employee"] == self.wh.id)
        self.assertEqual(row["auto_stars"], "4.5")          # среднее (5+4)/2
        self.assertEqual(row["ratings_count"], 2)
        self.assertEqual(row["parts"]["stars"], Decimal("4500"))  # 4.5 → 4500

    def test_manual_stars_override_auto(self):
        from finance.bonuses import build_bonuses
        from finance.models import EmployeeBonus
        from django.utils import timezone
        self._client_served("996700555", "Д")
        self.client.post("/api/public/rate/", {"phone": "996700555", "employee": self.wh.id, "stars": 5}, format="json")
        period = timezone.localdate().strftime("%Y-%m")
        eb = EmployeeBonus.objects.get_or_create(employee=self.wh, period=period)[0]
        eb.stars = Decimal("3"); eb.save()               # ручное переопределяет авто 5
        row = next(r for r in build_bonuses(period) if r["employee"] == self.wh.id)
        self.assertEqual(row["parts"]["stars"], Decimal("2000"))  # 3 → 2000
