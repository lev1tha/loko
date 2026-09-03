"""Тесты интеграции с kargoosh.kg: /api/kargo/… и доменные помощники."""
from datetime import date
from decimal import Decimal

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from express import kargo
from express.models import Client, ClientPrice, DeliveryStatus, KargoSync, Sale
from finance.models import Account, AppSettings, Branch

TOKEN = "test-kargo-token"
HDR = {"HTTP_X_KARGO_TOKEN": TOKEN}


def _settings():
    cfg = AppSettings.load()
    cfg.price_per_kg_usd = Decimal("3")
    cfg.usd_rate_som = Decimal("90")  # 270 сом/кг
    cfg.base_cost_per_kg_som = Decimal("100")
    cfg.save()


@override_settings(KARGO_API_TOKEN=TOKEN)
class KargoBase(APITestCase):
    def setUp(self):
        cache.clear()  # лимиты входа (throttle) живут в кеше между тестами
        _settings()
        self.acc = Account.objects.create(name="Касса Kargo", kind="CASH", currency="KGS", module="EXPRESS", legacy_kargo_card_id=1)
        self.osh = Branch.objects.create(name="Kargo · Ош", legacy_kargo_region="Ош")
        self.ksuu = Branch.objects.create(name="Kargo · Кара-суу", legacy_kargo_region="Кара-суу", price_per_kg_som=Decimal("255"))
        self.client_k = Client.objects.create(
            phone="700123456", name="Айбек", code="AL-12345", email="aibek@example.com",
            password_hash=kargo.legacy_md5("secret1"), branch=self.osh, legacy_kargo_id=7,
        )

    def post(self, url, data, **extra):
        return self.client.post(url, data, format="json", **HDR, **extra)

    def get(self, url, params=None):
        return self.client.get(url, params or {}, **HDR)


class TokenTests(KargoBase):
    def test_no_token_denied(self):
        r = self.client.get("/api/kargo/branches/")
        self.assertEqual(r.status_code, 403)

    def test_wrong_token_denied(self):
        r = self.client.get("/api/kargo/branches/", HTTP_X_KARGO_TOKEN="nope")
        self.assertEqual(r.status_code, 403)

    @override_settings(KARGO_API_TOKEN="")
    def test_empty_token_setting_fails_closed(self):
        r = self.client.get("/api/kargo/branches/", HTTP_X_KARGO_TOKEN="")
        self.assertEqual(r.status_code, 403)

    def test_jwt_not_required_and_token_ok(self):
        r = self.get("/api/kargo/branches/")
        self.assertEqual(r.status_code, 200)
        by_region = {b["region"]: b for b in r.data}
        self.assertEqual(by_region["Ош"]["code_prefix"], "AL-")
        self.assertEqual(by_region["Ош"]["price_per_kg_som"], "270.00")
        self.assertEqual(by_region["Кара-суу"]["code_prefix"], "OS-")
        self.assertEqual(by_region["Кара-суу"]["price_per_kg_som"], "255.00")


class PasswordTests(KargoBase):
    def test_legacy_md5_matches_php_scheme(self):
        # md5(md5(strrev("secret1")) . "test_ort") — посчитано отдельно по формуле PHP
        import hashlib
        inner = hashlib.md5("1terces".encode()).hexdigest()
        self.assertEqual(kargo.legacy_md5("secret1"), hashlib.md5((inner + "test_ort").encode()).hexdigest())

    def test_login_by_email_upgrades_hash(self):
        r = self.post("/api/kargo/auth/login/", {"login": "AIBEK@example.com", "password": "secret1"}, HTTP_X_KARGO_CLIENT_IP="1.2.3.4")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["client"]["code"], "AL-12345")
        self.client_k.refresh_from_db()
        self.assertFalse(kargo.is_legacy_hash(self.client_k.password_hash))
        self.assertTrue(self.client_k.check_password("secret1"))
        self.assertEqual(self.client_k.access_ip, "1.2.3.4")
        # повторный вход уже по Django-хешу
        r = self.post("/api/kargo/auth/login/", {"login": "aibek@example.com", "password": "secret1"})
        self.assertEqual(r.status_code, 200)

    def test_login_by_phone_variants(self):
        for login in ("+996 700 123 456", "0700123456", "700123456"):
            r = self.post("/api/kargo/auth/login/", {"login": login, "password": "secret1"})
            self.assertEqual(r.status_code, 200, login)

    def test_wrong_password_401(self):
        r = self.post("/api/kargo/auth/login/", {"login": "aibek@example.com", "password": "bad"})
        self.assertEqual(r.status_code, 401)

    def test_disabled_client_403(self):
        self.client_k.is_enabled = False
        self.client_k.save()
        r = self.post("/api/kargo/auth/login/", {"login": "aibek@example.com", "password": "secret1"})
        self.assertEqual(r.status_code, 403)

    def test_change_password(self):
        r = self.post("/api/kargo/auth/change-password/", {"client_id": self.client_k.id, "current_password": "bad", "new_password": "newpass1"})
        self.assertEqual(r.status_code, 400)
        r = self.post("/api/kargo/auth/change-password/", {"client_id": self.client_k.id, "current_password": "secret1", "new_password": "newpass1"})
        self.assertEqual(r.status_code, 200)
        self.client_k.refresh_from_db()
        self.assertTrue(self.client_k.check_password("newpass1"))

    def test_recovery_and_reset(self):
        r = self.post("/api/kargo/auth/recovery/", {"login": "700123456", "code": "AL-99999"})
        self.assertEqual(r.status_code, 400)
        r = self.post("/api/kargo/auth/recovery/", {"login": "700123456", "code": "al-12345"})
        self.assertEqual(r.status_code, 200, r.data)
        pc = r.data["pass_code"]
        r = self.post("/api/kargo/auth/reset-password/", {"pass_code": "wrong", "password": "brandnew1"})
        self.assertEqual(r.status_code, 400)
        r = self.post("/api/kargo/auth/reset-password/", {"pass_code": pc, "password": "brandnew1"})
        self.assertEqual(r.status_code, 200, r.data)
        self.client_k.refresh_from_db()
        self.assertTrue(self.client_k.check_password("brandnew1"))
        self.assertEqual(self.client_k.pass_code, "")
        # код одноразовый
        r = self.post("/api/kargo/auth/reset-password/", {"pass_code": pc, "password": "again123"})
        self.assertEqual(r.status_code, 400)

    def test_reset_expired_code(self):
        self.client_k.pass_code = "abc"
        self.client_k.pass_date = timezone.now() - timezone.timedelta(minutes=1)
        self.client_k.save()
        r = self.post("/api/kargo/auth/reset-password/", {"pass_code": "abc", "password": "again123"})
        self.assertEqual(r.status_code, 400)


class RegisterTests(KargoBase):
    def test_register_generates_code_by_region(self):
        r = self.post("/api/kargo/auth/register/", {
            "name": "Нурбек", "last_name": "Т.", "phone": "+996 555 000 111", "email": "nur@example.com",
            "password": "pass123", "region": "Кара-суу",
        })
        self.assertEqual(r.status_code, 201, r.data)
        c = Client.objects.get(email="nur@example.com")
        self.assertEqual(c.phone, "555000111")  # формат Kargo: 9 цифр
        self.assertTrue(c.code.startswith("OS-") and len(c.code) == 7)
        self.assertEqual(c.branch, self.ksuu)
        self.assertTrue(c.check_password("pass123"))
        self.assertIsNotNone(c.reg_date)

    def test_register_duplicate_email_or_phone(self):
        r = self.post("/api/kargo/auth/register/", {"name": "Xxx", "phone": "700999999", "email": "aibek@example.com", "password": "pass123", "branch": self.osh.id})
        self.assertEqual(r.status_code, 400)
        self.assertIn("email", r.data)
        r = self.post("/api/kargo/auth/register/", {"name": "Xxx", "phone": "+996700123456", "email": "x@example.com", "password": "pass123", "branch": self.osh.id})
        self.assertEqual(r.status_code, 400)
        self.assertIn("phone", r.data)

    def test_register_claims_qr_only_client(self):
        qr = Client.objects.create(phone="996777000222", name="QR-клиент")
        r = self.post("/api/kargo/auth/register/", {"name": "Полное имя", "phone": "777000222", "email": "qr@example.com", "password": "pass123", "branch": self.osh.id})
        self.assertEqual(r.status_code, 201, r.data)
        qr.refresh_from_db()
        self.assertEqual(qr.email, "qr@example.com")
        self.assertTrue(qr.code.startswith("AL-"))
        self.assertEqual(Client.objects.count(), 2)

    def test_register_requires_branch(self):
        r = self.post("/api/kargo/auth/register/", {"name": "Xxx", "phone": "700999999", "email": "z@example.com", "password": "pass123"})
        self.assertEqual(r.status_code, 400)


class ProfileTests(KargoBase):
    def test_get_profile_hides_hash(self):
        r = self.get(f"/api/kargo/clients/{self.client_k.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("password_hash", r.data)
        self.assertEqual(r.data["region"], "Ош")

    def test_patch_uniqueness(self):
        Client.objects.create(phone="700000001", code="AL-00001", email="o@example.com")
        r = self.client.patch(f"/api/kargo/clients/{self.client_k.id}/", {"code": "al-00001", "email": "O@example.com", "phone": "+996700000001"}, format="json", **HDR)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(set(r.data), {"code", "email", "phone"})
        r = self.client.patch(f"/api/kargo/clients/{self.client_k.id}/", {"name": "Айбек У.", "tg_id": "42", "code": "al-55555"}, format="json", **HDR)
        self.assertEqual(r.status_code, 200, r.data)
        self.client_k.refresh_from_db()
        self.assertEqual((self.client_k.name, self.client_k.tg_id, self.client_k.code), ("Айбек У.", "42", "AL-55555"))

    def test_unknown_client_404(self):
        self.assertEqual(self.get("/api/kargo/clients/999/").status_code, 404)


class OrderFlowTests(KargoBase):
    """Отгрузка → прибытие → выдача, как в PHP-админке, но данные в Loko."""

    def test_full_lifecycle(self):
        r = self.post("/api/kargo/orders/shipments/", {
            "region": "Ош", "shipment_date": "2026-09-01",
            "items": [{"tracking_number": "TRK1", "client_code": "12345"}, {"tracking_number": "TRK2", "client_code": "al-12345"}],
        })
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["created"], r.data["updated"]), (2, 0))
        s1 = Sale.objects.get(tracking_number="TRK1")
        self.assertEqual((s1.client_code, s1.delivery_status, s1.price_som, s1.paid_som), ("AL-12345", DeliveryStatus.TRANSIT, Decimal("0"), Decimal("0")))
        self.assertEqual(s1.shipment_date, date(2026, 9, 1))

        # трекинг по номеру — «в пути»
        r = self.get("/api/kargo/track/", {"number": "TRK2"})
        self.assertEqual((r.data["found"], r.data["status_code"], r.data["status_label"]), (True, 1, "В пути"))

        # повторная отгрузка того же трека → update, не дубль
        r = self.post("/api/kargo/orders/shipments/", {"branch": self.osh.id, "items": [{"tracking_number": "TRK1", "client_code": "AL-12345", "shipment_date": "2026-09-02"}]})
        self.assertEqual((r.data["created"], r.data["updated"]), (0, 1))
        self.assertEqual(Sale.objects.filter(tracking_number="TRK1").count(), 1)

        # прибытие: вес на первый трек, цена 270/кг (нет скидки, филиал без цены)
        r = self.post("/api/kargo/orders/arrive/", {"client_code": "AL-12345", "tracking_numbers": ["TRK1", "TRK2", "TRK3"], "weight_kg": "2.5", "region": "Ош"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["updated"], r.data["created"], r.data["unit_price_som"], r.data["client_found"]), (2, 1, "270.00", True))
        s1.refresh_from_db()
        self.assertEqual((s1.delivery_status, s1.weight_kg, s1.price_som, s1.paid_som), (DeliveryStatus.ARRIVED, Decimal("2.500"), Decimal("675.00"), Decimal("0")))
        self.assertEqual(s1.arrival_date, timezone.localdate())
        self.assertEqual(s1.cost_som, Decimal("250.00"))  # динамическая себестоимость 100 сом/кг
        s3 = Sale.objects.get(tracking_number="TRK3")
        self.assertEqual((s3.delivery_status, s3.price_som), (DeliveryStatus.ARRIVED, Decimal("0")))

        # кабинет клиента: «на складе» 3 шт, итог 675 сом
        r = self.get(f"/api/kargo/clients/{self.client_k.id}/orders/", {"status": "2"})
        self.assertEqual(len(r.data["orders"]), 3)
        self.assertEqual(r.data["totals"]["ARRIVED"]["price_som"], "675.00")
        self.assertEqual(r.data["totals"]["TRANSIT"]["count"], 0)

        # выдача: оплата на счёт, ОДДС-приток
        r = self.post("/api/kargo/orders/pickup/", {"client_code": "al-12345", "arrival_date": str(timezone.localdate()), "account": self.acc.id})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["count"], r.data["sum_som"]), (3, "675.00"))
        s1.refresh_from_db()
        self.assertEqual((s1.delivery_status, s1.paid_som, s1.payment_date, s1.account_id), (DeliveryStatus.DELIVERED, Decimal("675.00"), timezone.localdate(), self.acc.id))
        r = self.get("/api/kargo/track/", {"number": "TRK1"})
        self.assertEqual((r.data["status_code"], r.data["status_label"]), (3, "Отдан"))
        # второй раз выдавать нечего
        r = self.post("/api/kargo/orders/pickup/", {"client_code": "AL-12345", "arrival_date": str(timezone.localdate()), "account": self.acc.id})
        self.assertEqual(r.status_code, 400)

    def test_arrive_prices_discount_then_branch(self):
        self.client_k.discount = "250"
        self.client_k.save()
        r = self.post("/api/kargo/orders/arrive/", {"client_code": "AL-12345", "tracking_numbers": ["D1"], "weight_kg": "2", "branch": self.ksuu.id})
        self.assertEqual(r.data["unit_price_som"], "250.00")
        self.assertEqual(Sale.objects.get(tracking_number="D1").price_som, Decimal("500.00"))
        # без скидки — цена филиала Кара-суу (255)
        r = self.post("/api/kargo/orders/arrive/", {"client_code": "OS-1111", "tracking_numbers": ["D2"], "weight_kg": "1", "branch": self.ksuu.id})
        self.assertEqual((r.data["unit_price_som"], r.data["client_found"]), ("255.00", False))
        # ClientPrice тоже учитывается
        ClientPrice.objects.create(client_code="AL-12345", price_per_kg_som=Decimal("220"))
        self.client_k.discount = ""
        self.client_k.save()
        r = self.post("/api/kargo/orders/arrive/", {"client_code": "AL-12345", "tracking_numbers": ["D3"], "weight_kg": "1", "branch": self.osh.id})
        self.assertEqual(r.data["unit_price_som"], "220.00")

    def test_arrive_conflicts(self):
        Sale.objects.create(client_code="AL-77777", amount_mode="DIRECT", account=self.acc, price_som=Decimal("0"), paid_som=Decimal("0"),
                            date=date(2026, 9, 1), tracking_number="X1", delivery_status=DeliveryStatus.TRANSIT)
        r = self.post("/api/kargo/orders/arrive/", {"client_code": "AL-12345", "tracking_numbers": ["X1"], "weight_kg": "1", "branch": self.osh.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["conflicts"][0]["client_code"], "AL-77777")
        self.assertEqual(r.data["updated"] + r.data["created"], 0)

    def test_track_unknown_and_loko_sales_hidden(self):
        Sale.objects.create(client_code="Q", amount_mode="DIRECT", account=self.acc, price_som=Decimal("10"), date=date(2026, 9, 1), tracking_number="LOKO1")
        self.assertFalse(self.get("/api/kargo/track/", {"number": "LOKO1"}).data["found"])
        self.assertFalse(self.get("/api/kargo/track/", {"number": ""}).data["found"])

    def test_sync_status(self):
        r = self.get("/api/kargo/sync/")
        self.assertIsNone(r.data["last"])
        KargoSync.objects.create(mode="INCREMENTAL", ok=True, finished_at=timezone.now(), stats={"orders_created": 3})
        r = self.get("/api/kargo/sync/")
        self.assertEqual(r.data["last"]["stats"]["orders_created"], 3)
        self.assertIsNotNone(r.data["last_successful_at"])


class HelperTests(KargoBase):
    def test_phone_candidates(self):
        self.assertEqual(kargo.phone_candidates("+996 700 123 456"), ["996700123456", "700123456"])
        self.assertEqual(kargo.phone_candidates("0700123456"), ["0700123456", "700123456"])
        self.assertEqual(kargo.phone_candidates("700123456"), ["700123456", "996700123456"])
        self.assertEqual(kargo.canonical_phone("+996700123456"), "700123456")
        self.assertEqual(kargo.phone_candidates(""), [])

    def test_code_prefix(self):
        self.assertEqual(kargo.code_prefix("Бишкек"), ("GAA-", 5))
        self.assertEqual(kargo.code_prefix("Ош-район"), ("TRL-", 5))
        self.assertEqual(kargo.code_prefix(""), ("AL-", 5))
