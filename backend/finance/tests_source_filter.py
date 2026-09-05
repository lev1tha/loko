"""Фильтр источника отчётов: операции Loko vs перенесённая история Kargo Osh.

После импорта 171k заказов Kargo сводные отчёты показывали текущую работу Loko
вперемешку с чужой историей (выручка Express прыгнула с 10.7 млн до 255.8 млн).
Дефолт отчётов — ``source=loko``: дашборд ведёт себя как до импорта; история
доступна через ``?source=kargo``, всё вместе — ``?source=all``.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from express.models import DeliveryStatus, Sale
from finance.models import Account, AppSettings
from finance.reports import accounts_snapshot, breakdown, build_pnl, journal

User = get_user_model()

D = Decimal


class Base(APITestCase):
    """Один счёт Loko с продажей на 1 000 и один «перенесённый» счёт Kargo с
    продажей на 9 000 (legacy_kargo_id заполнен — это и есть признак истории)."""

    def setUp(self):
        cfg = AppSettings.load()
        cfg.express_cogs_pct = D("55")
        cfg.single_tax_pct = D("4")
        cfg.save()
        self.day = date(2026, 5, 17)

        self.loko_acc = Account.objects.create(
            name="Наличные", kind="CASH", currency="KGS", module="EXPRESS",
        )
        self.kargo_acc = Account.objects.create(
            name="Касса Ош (Kargo)", kind="CASH", currency="KGS", module="EXPRESS",
            initial_balance=D("500000"), legacy_kargo_card_id=77,
        )
        self.loko_sale = Sale.objects.create(
            client_code="LOKO-1", amount_mode=Sale.AmountMode.DIRECT, price_som=D("1000"),
            paid_som=D("1000"), account=self.loko_acc, date=self.day, payment_date=self.day,
        )
        # Историческая строка: как её кладёт import_kargoosh (bulk_create, без save()).
        self.kargo_sale = Sale.objects.create(
            client_code="OS-1234", amount_mode=Sale.AmountMode.DIRECT, price_som=D("9000"),
            paid_som=D("9000"), account=self.kargo_acc, date=self.day, payment_date=self.day,
            delivery_status=DeliveryStatus.DELIVERED, tracking_number="TRK-1",
        )
        Sale.objects.filter(pk=self.kargo_sale.pk).update(legacy_kargo_id=4242)
        self.kargo_sale.refresh_from_db()

        self.kassir = User.objects.create_user("kassir", password="x", role=User.Role.MANAGER)


class EngineTests(Base):
    def test_pnl_splits_by_source(self):
        loko = build_pnl(module="EXPRESS", source="loko")
        kargo = build_pnl(module="EXPRESS", source="kargo")
        both = build_pnl(module="EXPRESS")           # source=None → всё

        self.assertEqual(loko["revenue"], D("1000.00"))
        self.assertEqual(kargo["revenue"], D("9000.00"))
        self.assertEqual(both["revenue"], D("10000.00"))
        # Части складываются в целое — иначе фильтр где-то теряет или дублирует.
        self.assertEqual(loko["revenue"] + kargo["revenue"], both["revenue"])
        self.assertEqual(loko["cogs"] + kargo["cogs"], both["cogs"])

    def test_cogs_follows_filtered_revenue(self):
        """Себестоимость Express — 55% от выручки, значит она обязана считаться
        от ОТФИЛЬТРОВАННОЙ выручки, а не от общей."""
        loko = build_pnl(module="EXPRESS", source="loko")
        self.assertEqual(loko["cogs"], D("550.00"))

    def test_balances_exclude_kargo_cash_desks(self):
        names = {a["name"] for a in accounts_snapshot(source="loko")}
        self.assertEqual(names, {"Наличные"})
        self.assertEqual({a["name"] for a in accounts_snapshot(source="kargo")}, {"Касса Ош (Kargo)"})
        self.assertEqual(len(accounts_snapshot()), 2)

    def test_journal_and_breakdown_follow_source(self):
        j = journal(module="EXPRESS", source="loko")
        self.assertEqual([o["party"] for o in j["operations"] if o["effect"] == "Выручка"], ["LOKO-1"])
        b = breakdown("revenue", module="EXPRESS", source="kargo")
        self.assertEqual([i["title"] for i in b["items"]], ["Продажа · OS-1234"])


class ApiTests(Base):
    """Дефолт API — только Loko: главное требование, ради которого фильтр вводился."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.kassir)

    def test_default_is_loko_only(self):
        r = self.client.get("/api/reports/pnl/?module=EXPRESS")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(D(str(r.data["revenue"])), D("1000.00"))

    def test_explicit_sources(self):
        cases = {"kargo": D("9000.00"), "all": D("10000.00"), "loko": D("1000.00")}
        for source, expected in cases.items():
            with self.subTest(source=source):
                r = self.client.get(f"/api/reports/pnl/?module=EXPRESS&source={source}")
                self.assertEqual(D(str(r.data["revenue"])), expected)

    def test_unknown_source_falls_back_to_loko(self):
        """Мусор в параметре не должен молча раскрывать историю Kargo."""
        r = self.client.get("/api/reports/pnl/?module=EXPRESS&source=%D0%B1%D1%80%D0%B5%D0%B4")
        self.assertEqual(D(str(r.data["revenue"])), D("1000.00"))

    def test_balances_endpoint_defaults_to_loko(self):
        r = self.client.get("/api/reports/balances/")
        self.assertEqual({a["name"] for a in r.data}, {"Наличные"})
        r = self.client.get("/api/reports/balances/?source=all")
        self.assertEqual(len(r.data), 2)

    def test_cashflow_and_monthly_accept_source(self):
        r = self.client.get("/api/reports/cashflow/?module=EXPRESS&source=kargo")
        self.assertEqual(D(str(r.data["operating_inflow"])), D("9000.00"))
        r = self.client.get(
            "/api/reports/monthly/?module=EXPRESS&from=2026-05-01&to=2026-05-31&source=loko"
        )
        self.assertEqual(D(str(r.data["months"][0]["revenue"])), D("1000.00"))
