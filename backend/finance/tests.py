from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from finance.bonuses import (
    build_bonuses, tier_bonus,
    INSPECTION_TIERS, STARS_TIERS, TENURE_TIERS, TURNOVER_TIERS,
)
from finance.models import Account, AppSettings, Branch, EmployeeBonus
from express.models import Sale

User = get_user_model()


class BonusTierTests(TestCase):
    """Пороговые тарифы: берём наибольший достигнутый (иначе 0)."""

    def test_inspection(self):
        self.assertEqual(tier_bonus(Decimal("2.9"), INSPECTION_TIERS), Decimal("0"))
        self.assertEqual(tier_bonus(Decimal("3"), INSPECTION_TIERS), Decimal("1000"))
        self.assertEqual(tier_bonus(Decimal("4.5"), INSPECTION_TIERS), Decimal("2000"))
        self.assertEqual(tier_bonus(Decimal("5"), INSPECTION_TIERS), Decimal("2500"))

    def test_turnover(self):
        self.assertEqual(tier_bonus(Decimal("2999"), TURNOVER_TIERS), Decimal("0"))
        self.assertEqual(tier_bonus(Decimal("3000"), TURNOVER_TIERS), Decimal("2000"))
        self.assertEqual(tier_bonus(Decimal("7000"), TURNOVER_TIERS), Decimal("8000"))
        self.assertEqual(tier_bonus(Decimal("12000"), TURNOVER_TIERS), Decimal("12000"))

    def test_stars_and_tenure(self):
        self.assertEqual(tier_bonus(None, STARS_TIERS), Decimal("0"))
        self.assertEqual(tier_bonus(Decimal("5"), STARS_TIERS), Decimal("6000"))
        self.assertEqual(tier_bonus(2, TENURE_TIERS), Decimal("0"))
        self.assertEqual(tier_bonus(3, TENURE_TIERS), Decimal("1000"))
        self.assertEqual(tier_bonus(24, TENURE_TIERS), Decimal("3500"))


class BonusComputeTests(APITestCase):
    """Итог = оклад + дисциплина + проверка + оборот + звёзды + стаж + отзывы."""

    def setUp(self):
        cfg = AppSettings.load()
        cfg.price_per_kg_usd = Decimal("3"); cfg.usd_rate_som = Decimal("90")
        cfg.base_cost_per_kg_som = Decimal("100"); cfg.save()
        self.branch = Branch.objects.create(name="Ф", is_default=True)
        self.acc = Account.objects.create(name="Касса", kind="CASH", currency="KGS", module="EXPRESS")
        self.period = timezone.localdate().strftime("%Y-%m")

    def test_total_sums_all_parts(self):
        wh = User.objects.create_user("wh_b", password="p", role=User.Role.WAREHOUSE, branch=self.branch)
        # Стаж ~8 мес назад → tenure ≥ 6 → 2000.
        wh.date_joined = timezone.now() - timedelta(days=250)
        wh.save(update_fields=["date_joined"])
        # Оборот филиала за месяц: 3200 кг → 2000.
        Sale.objects.create(
            client_code="A", amount_mode="WEIGHT", weight_kg=Decimal("3200"),
            account=self.acc, branch=self.branch, date=timezone.localdate(),
        )
        # Ручные: дисциплина(2000), проверка 4(1500), звёзды 5(6000), 2 отзыва(400).
        EmployeeBonus.objects.create(
            employee=wh, period=self.period, discipline_ok=True,
            inspection_score=Decimal("4"), stars=Decimal("5"), reviews_count=2,
        )
        row = next(r for r in build_bonuses(self.period) if r["employee"] == wh.id)
        self.assertEqual(row["turnover_kg"], Decimal("3200"))
        self.assertEqual(row["parts"]["turnover"], Decimal("2000"))
        self.assertEqual(row["parts"]["tenure"], Decimal("2000"))
        self.assertEqual(row["parts"]["stars"], Decimal("6000"))
        self.assertEqual(row["parts"]["reviews"], Decimal("400"))
        # 20000 + 2000 + 1500 + 2000 + 6000 + 2000 + 400
        self.assertEqual(row["total"], Decimal("33900"))

    def test_base_only_when_no_data(self):
        op = User.objects.create_user("op_b", password="p", role=User.Role.OPERATOR, branch=self.branch)
        row = next(r for r in build_bonuses(self.period) if r["employee"] == op.id)
        # Нет оборота/звёзд/стажа/отзывов → только оклад + дисциплина.
        self.assertEqual(row["total"], Decimal("22000"))

    def test_patch_manual_field_changes_total(self):
        self.client.force_authenticate(
            User.objects.create_user("mgr_b", password="p", role=User.Role.MANAGER)
        )
        op = User.objects.create_user("op_c", password="p", role=User.Role.OPERATOR, branch=self.branch)
        # Строка создаётся при расчёте.
        rows = build_bonuses(self.period)
        bid = next(r for r in rows if r["employee"] == op.id)["id"]
        r = self.client.patch(f"/api/bonuses/{bid}/", {"stars": "5", "discipline_ok": False}, content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        row = next(x for x in build_bonuses(self.period) if x["employee"] == op.id)
        # 20000 + 0(дисциплина снята) + 6000(звёзды 5) = 26000
        self.assertEqual(row["total"], Decimal("26000"))


class BranchQrTests(APITestCase):
    """QR филиала: ссылка track_url + генерация SVG/PNG; закрыт для оператора."""

    def setUp(self):
        from django.conf import settings
        self.settings_url = settings.PUBLIC_SITE_URL.rstrip("/")
        self.admin = User.objects.create_user("admin_qr", password="Zx9!mfP2qL", role=User.Role.ADMIN)
        self.branch = Branch.objects.create(name="Ф-QR", is_default=False)

    def _row(self, data):
        rows = data if isinstance(data, list) else data.get("results", [])
        return next(x for x in rows if x["id"] == self.branch.id)

    def test_track_url_points_to_public_track_page(self):
        self.client.force_authenticate(self.admin)
        row = self._row(self.client.get("/api/branches/").data)
        self.assertEqual(row["track_url"], f"{self.settings_url}/track?b={self.branch.id}")

    def test_qr_svg_and_png(self):
        self.client.force_authenticate(self.admin)
        r = self.client.get(f"/api/branches/{self.branch.id}/qr/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/svg+xml")
        self.assertIn(b"<svg", r.content)
        r2 = self.client.get(f"/api/branches/{self.branch.id}/qr/?fmt=png")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2["Content-Type"], "image/png")
        self.assertEqual(r2.content[:8], b"\x89PNG\r\n\x1a\n")  # PNG magic

    def test_qr_denied_for_operator(self):
        op = User.objects.create_user("op_qr", password="Zx9!mfP2qL", role=User.Role.OPERATOR, branch=self.branch)
        self.client.force_authenticate(op)
        self.assertEqual(self.client.get(f"/api/branches/{self.branch.id}/qr/").status_code, 403)

    def test_qr_requires_auth(self):
        self.assertEqual(self.client.get(f"/api/branches/{self.branch.id}/qr/").status_code, 401)
