"""Страницы «Доход» и «Расход» директора: права, область направления, статьи."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from finance.models import Account, AppSettings, Expense, OtherIncome
from finance.reports import build_cashflow, build_pnl

User = get_user_model()


class Base(APITestCase):
    def setUp(self):
        AppSettings.load()
        self.ex_cash = Account.objects.create(name="Нал Express", kind="CASH", currency="KGS", module="EXPRESS")
        self.ex_bank = Account.objects.create(name="Банк Express", kind="BANK", currency="KGS", module="EXPRESS")
        self.bz = Account.objects.create(name="Бизнес", kind="BANK", currency="KGS", module="BUSINESS")
        self.dir_ex = User.objects.create_user("dir_ex", password="x", role=User.Role.DIRECTOR, module="EXPRESS")
        self.dir_bz = User.objects.create_user("dir_bz", password="x", role=User.Role.DIRECTOR, module="BUSINESS")
        self.op = User.objects.create_user("op", password="x", role=User.Role.OPERATOR, first_name="Алмаз")
        self.kassir = User.objects.create_user("kassir", password="x", role=User.Role.MANAGER)

    def post(self, url, data):
        return self.client.post(url, data, format="json")


class AccessTests(Base):
    def test_pickers(self):
        self.client.force_authenticate(self.dir_ex)
        r = self.client.get("/api/expenses/accounts/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual({a["name"] for a in r.data}, {"Нал Express", "Банк Express"})
        self.assertNotIn("current_balance", r.data[0])
        r = self.client.get("/api/expenses/employees/")
        self.assertIn("Алмаз", [u["name"] for u in r.data])
        self.client.force_authenticate(self.op)
        self.assertEqual(self.client.get("/api/expenses/accounts/").status_code, 403)
        self.assertEqual(self.post("/api/expenses/", {}).status_code, 403)

    def test_director_scopes_and_cannot_edit(self):
        self.client.force_authenticate(self.dir_ex)
        # директор может писать в любое направление (видит оба)
        r = self.post("/api/other-income/", {"account": self.bz.id, "amount": "99", "description": "biz", "date": "2026-09-04"})
        self.assertEqual(r.status_code, 201, r.data)
        r = self.post("/api/other-income/", {"account": self.ex_cash.id, "amount": "10", "description": "x", "date": "2026-09-04"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.client.patch(f"/api/other-income/{r.data['id']}/", {"amount": "5"}, format="json").status_code, 403)
        # список: по умолчанию своё направление, ?module= переключает, all — всё
        self.assertEqual([x["description"] for x in self.client.get("/api/other-income/").data["results"]], ["x"])
        self.assertEqual([x["description"] for x in self.client.get("/api/other-income/", {"module": "BUSINESS"}).data["results"]], ["biz"])
        self.assertEqual(len(self.client.get("/api/other-income/", {"module": "all"}).data["results"]), 2)
        r = self.client.get("/api/expenses/accounts/", {"module": "BUSINESS"})
        self.assertEqual([a["name"] for a in r.data], ["Бизнес"])
        # чужую запись удалить нельзя, свою — можно
        other = OtherIncome.objects.create(account=self.ex_cash, amount=Decimal("1"), description="k", date="2026-09-04", created_by=self.kassir)
        self.assertEqual(self.client.delete(f"/api/other-income/{other.id}/").status_code, 400)
        mine = OtherIncome.objects.get(description="x")
        self.assertEqual(self.client.delete(f"/api/other-income/{mine.id}/").status_code, 204)


class IncomeTests(Base):
    def test_income_hits_revenue_and_cashflow(self):
        self.client.force_authenticate(self.dir_ex)
        r = self.post("/api/other-income/", {"account": self.ex_cash.id, "amount": "1500", "description": "Упаковка — оптовик", "date": "2026-09-04"})
        self.assertEqual(r.status_code, 201, r.data)
        pnl = build_pnl("2026-09-01", "2026-09-30", module="EXPRESS")
        self.assertEqual(Decimal(pnl["other_income"]), Decimal("1500.00"))
        self.assertEqual(OtherIncome.objects.get().created_by, self.dir_ex)


class ExpenseTests(Base):
    def _exp(self, **kw):
        body = {"account": self.ex_cash.id, "amount": "1000", "paid_amount": "1000", "date": "2026-09-04", "payment_date": "2026-09-04", "description": ""}
        body.update(kw)
        return self.post("/api/expenses/", body)

    def test_operating_salary_with_employee(self):
        self.client.force_authenticate(self.dir_ex)
        r = self._exp(category="OPEX", opex_article="PAYROLL", employee=self.op.id, description="Зарплата: Алмаз")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["employee_name"], "Алмаз")
        e = Expense.objects.get()
        self.assertEqual((e.employee, e.created_by), (self.op, self.dir_ex))
        pnl = build_pnl("2026-09-01", "2026-09-30", module="EXPRESS")
        self.assertEqual(Decimal(pnl["operating_expenses"]), Decimal("1000.00"))

    def test_employee_ignored_for_non_salary(self):
        self.client.force_authenticate(self.dir_ex)
        r = self._exp(category="OPEX", opex_article="RENT", employee=self.op.id)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIsNone(Expense.objects.get().employee)

    def test_investing_other_requires_comment(self):
        self.client.force_authenticate(self.dir_ex)
        r = self._exp(category="INVEST", opex_article="INVEST_OTHER")
        self.assertEqual(r.status_code, 400)
        self.assertIn("description", r.data)
        r = self._exp(category="INVEST", opex_article="INVEST_OTHER", description="Вывеска")
        self.assertEqual(r.status_code, 201, r.data)
        r = self._exp(category="INVEST", opex_article="PURCHASE", amount="500", paid_amount="500")
        self.assertEqual(r.status_code, 201, r.data)
        cf = build_cashflow("2026-09-01", "2026-09-30", module="EXPRESS")
        self.assertEqual(Decimal(cf["investing_outflow"]), Decimal("1500.00"))
        pnl = build_pnl("2026-09-01", "2026-09-30", module="EXPRESS")
        self.assertEqual(Decimal(pnl["operating_expenses"]), Decimal("0.00"))  # инвестиции не в ОПиУ

    def test_financing_owner_and_single_tax(self):
        self.client.force_authenticate(self.dir_ex)
        r = self._exp(category="OWNER", opex_article=None, amount="3000", paid_amount="3000")
        self.assertEqual(r.status_code, 201, r.data)
        r = self._exp(category="FINANCING", opex_article="SINGLE_TAX", amount="400", paid_amount="400")
        self.assertEqual(r.status_code, 201, r.data)
        cf = build_cashflow("2026-09-01", "2026-09-30", module="EXPRESS")
        self.assertEqual(Decimal(cf["owner_withdrawals"]), Decimal("3000.00"))
        self.assertEqual(Decimal(cf["financing_loan_out"]), Decimal("400.00"))
        self.assertEqual(Decimal(cf["closing_balance"]), Decimal("-3400.00"))

    def test_article_must_match_section(self):
        self.client.force_authenticate(self.dir_ex)
        self.assertEqual(self._exp(category="OPEX", opex_article="SINGLE_TAX").status_code, 400)
        self.assertEqual(self._exp(category="INVEST", opex_article="RENT").status_code, 400)
