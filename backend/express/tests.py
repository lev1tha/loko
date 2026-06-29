from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from finance.models import Account, AppSettings
from express.models import ClientPrice, Sale

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
        op = User.objects.create_user("op_q", password="pass1234", role=User.Role.OPERATOR)
        self.client.force_authenticate(op)
        r = self.client.post("/api/sales/quote/", {"weight_kg": "4", "client_code": "VIP"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["price_som"], Decimal("1000.00"))
        # Оператору не раскрываем ставку за кг — только итог.
        self.assertNotIn("price_per_kg_usd", r.data)
