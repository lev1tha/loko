"""Единый формат телефона клиента и склейка дублей."""
from django.core.cache import cache
from django.core.management import call_command
from io import StringIO
from rest_framework.test import APITestCase

from express.models import Client, WarehouseOrder
from finance.models import Branch


class PhoneTests(APITestCase):
    def test_normalize_variants(self):
        for raw in ("+996 700 12 34 56", "0700123456", "700123456", "996700123456", "700-123-456"):
            self.assertEqual(Client.normalize_phone(raw), "700123456", raw)
        self.assertEqual(Client.normalize_phone("+7 916 000 11 22"), "79160001122")  # не киргизский — как есть

    def test_qr_finds_imported_kargo_client(self):
        cache.clear()
        b = Branch.objects.create(name="Точка", is_default=True)
        kargo = Client.objects.create(phone="700123456", name="Айбек", code="AL-1", legacy_kargo_id=5)
        r = self.client.post("/api/public/intake/", {"branch": b.id, "phone": "+996 700 123 456", "name": "Айбек Т.", "client_codes": ["AL-1"]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(WarehouseOrder.objects.get().client, kargo)
        r = self.client.get("/api/public/track/", {"phone": "0700123456"})
        self.assertTrue(r.data["found"])


class MergeCommandTests(APITestCase):
    def test_merge_keeps_kargo_account_and_moves_orders(self):
        b = Branch.objects.create(name="Точка", is_default=True)
        kargo = Client.objects.create(phone="700123456", name="Айбек", code="AL-1", legacy_kargo_id=5)
        qr = Client(phone="996700123456", name="Айбек QR")
        qr.save()
        o = WarehouseOrder.objects.create(branch=b, client=qr, client_codes=["AL-1"])
        other = Client(phone="0555000111", name="Б")
        other.save()
        out = StringIO()
        call_command("merge_duplicate_clients", "--dry-run", stdout=out)
        self.assertEqual(Client.objects.count(), 3)
        call_command("merge_duplicate_clients", stdout=out)
        self.assertEqual(Client.objects.count(), 2)
        kargo.refresh_from_db(); o.refresh_from_db()
        self.assertEqual((o.client, kargo.phone, kargo.name), (kargo, "700123456", "Айбек"))
        self.assertEqual(Client.objects.get(name="Б").phone, "555000111")
        self.assertIn("Склеено дублей: 1", out.getvalue())


class KnownClientIntakeTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.b = Branch.objects.create(name="Точка", is_default=True)
        self.kargo = Client.objects.create(phone="700123456", name="Айбек", code="AL-12345", legacy_kargo_id=5)

    def test_track_returns_code_and_parcels(self):
        from decimal import Decimal
        from express.models import Sale, DeliveryStatus
        from finance.models import Account
        acc = Account.objects.create(name="К", kind="CASH", currency="KGS", module="EXPRESS")
        Sale.objects.create(client_code="AL-12345", amount_mode="DIRECT", account=acc, price_som=Decimal("0"), paid_som=Decimal("0"),
                            date="2026-09-01", shipment_date="2026-09-01", tracking_number="T1", delivery_status=DeliveryStatus.TRANSIT, legacy_kargo_id=1)
        Sale.objects.create(client_code="AL-12345", amount_mode="DIRECT", account=acc, price_som=Decimal("540"), paid_som=Decimal("0"), weight_kg=Decimal("2"),
                            date="2026-09-03", arrival_date="2026-09-03", tracking_number="T2", delivery_status=DeliveryStatus.ARRIVED, legacy_kargo_id=2)
        r = self.client.get("/api/public/track/", {"phone": "+996 700 123 456"})
        self.assertEqual(r.data["client"]["code"], "AL-12345")
        self.assertEqual([(p["tracking_number"], p["status"], p["price_som"]) for p in r.data["parcels"]], [("T2", "ARRIVED", "540.00"), ("T1", "TRANSIT", None)])

    def test_intake_without_codes_uses_client_code(self):
        r = self.client.post("/api/public/intake/", {"branch": self.b.id, "phone": "0700123456"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["codes"], ["AL-12345"])
        self.assertEqual(WarehouseOrder.objects.get().client_codes, ["AL-12345"])

    def test_intake_without_codes_for_unknown_client_fails(self):
        r = self.client.post("/api/public/intake/", {"branch": self.b.id, "phone": "0555000111", "name": "Новый"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("client_codes", r.data)
