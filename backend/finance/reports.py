"""Financial reporting engine for Loko (Express + Business).

Accrual vs. cash separation (как в реальном учёте Локо):
  * ОПиУ (P&L)       — по НАЧИСЛЕНИЮ, по «дате операции» (Sale.date / Expense.date).
  * ОДДС (Cash Flow) — по ОПЛАТЕ, по «дате оплаты» (Sale.payment_date / Expense.payment_date).

All amounts are consolidated into KGS (сом); CNY → KGS by AppSettings.cny_to_kgs_rate.
"""

from decimal import Decimal

from django.db.models import Sum

from .models import (
    Account,
    AppSettings,
    Currency,
    Expense,
    ExpenseCategory,
    OpexArticle,
)

ZERO = Decimal("0.00")


def _rate() -> Decimal:
    return AppSettings.load().cny_to_kgs_rate


def to_kgs(amount: Decimal, currency: str) -> Decimal:
    amount = amount or ZERO
    if currency == Currency.CNY:
        return (amount * _rate()).quantize(ZERO)
    return amount


def _pct(part: Decimal, whole: Decimal) -> Decimal:
    if not whole:
        return ZERO
    return (part / whole * Decimal("100")).quantize(Decimal("0.1"))


def _kinds_for_payment(payment: str):
    if payment == "cash":
        return [Account.Kind.CASH]
    if payment == "noncash":
        return [Account.Kind.BANK]
    return [Account.Kind.CASH, Account.Kind.BANK]


def _between(qs, date_from, date_to, field):
    if date_from:
        qs = qs.filter(**{f"{field}__gte": date_from})
    if date_to:
        qs = qs.filter(**{f"{field}__lte": date_to})
    return qs


# ---------------------------------------------------------------------------
# Express sales
# ---------------------------------------------------------------------------
def _by_module(qs, module):
    return qs.filter(account__module=module) if module else qs


def _sales(date_from, date_to, kinds, field, module=None):
    from express.models import Sale

    qs = _by_module(Sale.objects.filter(account__kind__in=kinds), module)
    return _between(qs, date_from, date_to, field)


# ---------------------------------------------------------------------------
# Expenses (accrual = amount/date ; cash = paid_amount/payment_date)
# ---------------------------------------------------------------------------
def _expense_qs(date_from, date_to, kinds, field, category=None, article=None, module=None):
    qs = _by_module(Expense.objects.filter(account__kind__in=kinds), module)
    if category is not None:
        qs = qs.filter(category=category)
    if article is not None:
        qs = qs.filter(opex_article=article)
    return _between(qs, date_from, date_to, field)


def _sum_kgs(qs, value_field):
    total = ZERO
    for row in qs.values("account__currency").annotate(s=Sum(value_field)):
        total += to_kgs(row["s"] or ZERO, row["account__currency"])
    return total


def _expense_accrual(date_from, date_to, kinds, category=None, article=None, module=None):
    qs = _expense_qs(date_from, date_to, kinds, "date", category, article, module)
    return _sum_kgs(qs, "amount"), qs.count()


def _expense_paid(date_from, date_to, kinds, category=None, module=None):
    qs = _expense_qs(date_from, date_to, kinds, "payment_date", category, module=module)
    return _sum_kgs(qs, "paid_amount"), qs.count()


# ---------------------------------------------------------------------------
# Deposits (Business)
# ---------------------------------------------------------------------------
def _recognized_deposits(date_from, date_to, module=None):
    from business.models import Deposit

    qs = _by_module(Deposit.objects.filter(status=Deposit.Status.RECOGNIZED), module)
    qs = _between(qs, date_from, date_to, "recognized_date")
    total = ZERO
    for row in qs.values("currency").annotate(s=Sum("amount")):
        total += to_kgs(row["s"] or ZERO, row["currency"])
    return total, qs.count()


def _deposits_received(date_from, date_to, module=None):
    from business.models import Deposit

    qs = _by_module(Deposit.objects.all(), module)
    qs = _between(qs, date_from, date_to, "date")
    total = ZERO
    for row in qs.values("currency").annotate(s=Sum("amount")):
        total += to_kgs(row["s"] or ZERO, row["currency"])
    return total, qs.count()


def _opex_breakdown(date_from, date_to, kinds, module=None):
    articles = {}
    total = ZERO
    count = 0
    for art in OpexArticle:
        amount, cnt = _expense_accrual(date_from, date_to, kinds, ExpenseCategory.OPEX, art.value, module)
        articles[art.value] = {"label": art.label, "amount": amount, "count": cnt}
        total += amount
        count += cnt
    return {"articles": articles, "total": total, "count": count}


# ===========================================================================
# ОПиУ (P&L) — по начислению
# ===========================================================================
def build_pnl(date_from=None, date_to=None, payment="all", tax_rate=None, module=None):
    kinds = _kinds_for_payment(payment)
    if tax_rate is None:
        tax_rate = AppSettings.load().profit_tax_rate
    tax_rate = Decimal(str(tax_rate))

    sales = _sales(date_from, date_to, kinds, "date", module)
    express_revenue = sales.aggregate(s=Sum("price_som"))["s"] or ZERO
    deposit_revenue, deposit_count = _recognized_deposits(date_from, date_to, module)
    revenue = express_revenue + deposit_revenue

    # Себестоимость = динамическая по продажам Express + закуп товара (Business).
    express_cogs = sales.aggregate(s=Sum("cost_som"))["s"] or ZERO
    business_cogs, _ = _expense_accrual(date_from, date_to, kinds, ExpenseCategory.COGS, module=module)
    cogs = express_cogs + business_cogs
    gross_profit = revenue - cogs

    opex = _opex_breakdown(date_from, date_to, kinds, module)
    operating_profit = gross_profit - opex["total"]

    other_expenses, other_count = _expense_accrual(date_from, date_to, kinds, ExpenseCategory.OTHER, module=module)
    other_income = ZERO          # задел: прочие доходы
    financial_expenses = ZERO    # задел: финансовые расходы
    pre_tax_profit = operating_profit + other_income - other_expenses - financial_expenses

    tax = (max(pre_tax_profit, ZERO) * tax_rate / Decimal("100")).quantize(ZERO)
    net_profit = pre_tax_profit - tax

    expense_total_count = opex["count"] + other_count

    return {
        "report": "PNL",
        "period": {"from": date_from, "to": date_to},
        "payment": payment,
        "express_revenue": express_revenue,
        "deposit_revenue": deposit_revenue,
        "revenue": revenue,
        "cogs": cogs,
        "gross_profit": gross_profit,
        "gross_margin_pct": _pct(gross_profit, revenue),
        "opex_articles": opex["articles"],
        "operating_expenses": opex["total"],
        "operating_profit": operating_profit,
        "other_income": other_income,
        "other_expenses": other_expenses,
        "financial_expenses": financial_expenses,
        "pre_tax_profit": pre_tax_profit,
        "tax_rate": tax_rate,
        "tax": tax,
        "net_profit": net_profit,
        "net_margin_pct": _pct(net_profit, revenue),
        "sales_count": sales.count(),
        "deposit_count": deposit_count,
        "opex_count": opex["count"],
        "operations": {"income": sales.count() + deposit_count, "expense": expense_total_count},
    }


# ===========================================================================
# Cash helpers for opening / closing balances (consolidated KGS)
# ===========================================================================
def _consolidated_cash(upper_date, inclusive, module=None):
    """Consolidated KGS cash counting flows up to a boundary date.

    inclusive=True → flows with date <= upper_date (closing).
    inclusive=False → flows with date <  upper_date (opening).
    """
    op = "lte" if inclusive else "lt"

    def filt(qs, field):
        if upper_date is None:
            return qs if inclusive else qs.none()
        return qs.filter(**{f"{field}__{op}": upper_date})

    total = ZERO
    accounts = Account.objects.filter(module=module) if module else Account.objects.all()
    for acc in accounts:
        bal = acc.initial_balance
        bal += filt(acc.sales, "payment_date").aggregate(s=Sum("paid_som"))["s"] or ZERO
        bal += filt(acc.deposits, "date").aggregate(s=Sum("amount"))["s"] or ZERO
        bal -= filt(acc.expenses, "payment_date").aggregate(s=Sum("paid_amount"))["s"] or ZERO
        bal += filt(acc.incoming_transfers, "date").aggregate(s=Sum("to_amount"))["s"] or ZERO
        bal -= filt(acc.outgoing_transfers, "date").aggregate(s=Sum("amount"))["s"] or ZERO
        total += to_kgs(bal, acc.currency)
    return total


# ===========================================================================
# ОДДС (Cash Flow) — по оплате
# ===========================================================================
def build_cashflow(date_from=None, date_to=None, payment="all", module=None):
    kinds = _kinds_for_payment(payment)

    sales = _sales(date_from, date_to, kinds, "payment_date", module)
    express_inflow = sales.aggregate(s=Sum("paid_som"))["s"] or ZERO
    deposits_inflow, deposits_count = _deposits_received(date_from, date_to, module)
    operating_inflow = express_inflow + deposits_inflow

    opex, opex_cnt = _expense_paid(date_from, date_to, kinds, ExpenseCategory.OPEX, module)
    cogs_paid, cogs_cnt = _expense_paid(date_from, date_to, kinds, ExpenseCategory.COGS, module)
    supplier, sup_cnt = _expense_paid(date_from, date_to, kinds, ExpenseCategory.SUPPLIER, module)
    other, other_cnt = _expense_paid(date_from, date_to, kinds, ExpenseCategory.OTHER, module)
    owner, owner_cnt = _expense_paid(date_from, date_to, kinds, ExpenseCategory.OWNER, module)

    operating_outflow = opex + cogs_paid + supplier + other
    net_operating = operating_inflow - operating_outflow
    financing_outflow = owner  # изъятие собственника
    total_outflow = operating_outflow + financing_outflow
    net_cash_flow = operating_inflow - total_outflow

    opening = _consolidated_cash(date_from, inclusive=False, module=module)
    closing = _consolidated_cash(date_to, inclusive=True, module=module)

    expense_count = opex_cnt + sup_cnt + other_cnt + owner_cnt

    return {
        "report": "CASHFLOW",
        "period": {"from": date_from, "to": date_to},
        "payment": payment,
        "opening_balance": opening,
        "express_inflow": express_inflow,
        "deposits_inflow": deposits_inflow,
        "operating_inflow": operating_inflow,
        "opex": opex,
        "cogs_paid": cogs_paid,
        "supplier_payments": supplier,
        "other_outflow": other,
        "operating_outflow": operating_outflow,
        "net_operating": net_operating,
        "owner_withdrawals": owner,
        "financing_outflow": financing_outflow,
        "total_outflow": total_outflow,
        "net_cash_flow": net_cash_flow,
        "closing_balance": closing,
        "payment_breakdown": _payment_breakdown(date_from, date_to, module),
        "operations": {"income": sales.count() + deposits_count, "expense": expense_count},
    }


def _payment_breakdown(date_from, date_to, module=None):
    """Свод оплат: приход/расход по каждому счёту (методу), в KGS, по оплате."""
    rows = []
    accounts = Account.objects.filter(module=module) if module else Account.objects.all()
    for acc in accounts:
        sales_in = _between(acc.sales.all(), date_from, date_to, "payment_date")
        dep_in = _between(acc.deposits.all(), date_from, date_to, "date")
        exp_out = _between(acc.expenses.all(), date_from, date_to, "payment_date")
        income = (sales_in.aggregate(s=Sum("paid_som"))["s"] or ZERO) + (
            dep_in.aggregate(s=Sum("amount"))["s"] or ZERO
        )
        expense = exp_out.aggregate(s=Sum("paid_amount"))["s"] or ZERO
        income_cnt = sales_in.count() + dep_in.count()
        expense_cnt = exp_out.count()
        if income or expense or income_cnt or expense_cnt:
            rows.append(
                {
                    "account": acc.name,
                    "currency": acc.currency,
                    "kind": acc.kind,
                    "income": income,
                    "expense": expense,
                    "income_kgs": to_kgs(income, acc.currency),
                    "expense_kgs": to_kgs(expense, acc.currency),
                    "income_count": income_cnt,
                    "expense_count": expense_cnt,
                }
            )
    return rows


# ===========================================================================
# Balances & debts
# ===========================================================================
def accounts_snapshot(module=None):
    qs = Account.objects.all()
    if module:
        qs = qs.filter(module=module)
    result = []
    for acc in qs:
        bal = acc.current_balance
        result.append(
            {
                "id": acc.id,
                "name": acc.name,
                "kind": acc.kind,
                "currency": acc.currency,
                "module": acc.module,
                "initial_balance": acc.initial_balance,
                "income": acc.income_total(),
                "deposits": acc.deposit_total(),
                "expense": acc.expense_total(),
                "transfers_in": acc.transfers_in_total(),
                "transfers_out": acc.transfers_out_total(),
                "current_balance": bal,
                "current_balance_kgs": to_kgs(bal, acc.currency),
            }
        )
    return result


def debts_summary():
    """Дебиторка/кредиторка: Business (Debt) + Express (начисление − оплата)."""
    from business.models import Debt
    from express.models import Sale

    biz = {}
    for kind in Debt.Kind:
        rows = (
            Debt.objects.filter(kind=kind.value, status=Debt.Status.OPEN)
            .values("currency")
            .annotate(s=Sum("amount"))
        )
        biz[kind.value] = sum((to_kgs(r["s"] or ZERO, r["currency"]) for r in rows), ZERO)

    # Express receivable = неоплаченная часть продаж (начисление − оплата).
    s = Sale.objects.aggregate(a=Sum("price_som"), p=Sum("paid_som"))
    express_receivable = (s["a"] or ZERO) - (s["p"] or ZERO)
    e = Expense.objects.values("account__currency").annotate(a=Sum("amount"), p=Sum("paid_amount"))
    express_payable = ZERO
    for row in e:
        express_payable += to_kgs((row["a"] or ZERO) - (row["p"] or ZERO), row["account__currency"])

    payable = biz.get(Debt.Kind.PAYABLE, ZERO) + express_payable
    receivable = biz.get(Debt.Kind.RECEIVABLE, ZERO) + express_receivable
    return {
        "payable": payable,
        "receivable": receivable,
        "net": receivable - payable,
        "business_payable": biz.get(Debt.Kind.PAYABLE, ZERO),
        "business_receivable": biz.get(Debt.Kind.RECEIVABLE, ZERO),
        "express_receivable": express_receivable,
        "express_payable": express_payable,
    }


def _norm_client(name: str) -> str:
    """Нормализуем имя клиента: убираем префикс «Закуп товара —», скобки и хвосты."""
    import re

    if not name:
        return "—"
    s = str(name)
    if "—" in s:
        s = s.split("—", 1)[1]
    s = re.sub(r"\s*\(.*?\)", "", s)  # убрать «(мбанк)» и т.п.
    return s.strip() or "—"


def _order_status(rev, adv_client, cost):
    if adv_client and not rev:
        return "Аванс/депозит — не признан"
    if rev and cost:
        return "Заказ закрывается"
    if rev and not cost:
        return "Есть приход, закуп не отражён"
    if cost and not rev:
        return "Есть закуп без прихода"
    return "—"


def business_orders(date_from=None, date_to=None):
    """«Заказы Business» по клиентам + детализация операций (даты/ID).

    Выручка — признанные депозиты; закуп — расходы «Себестоимость»; аванс клиента —
    непризнанные депозиты; аванс поставщику — расходы «Оплата/аванс поставщику».
    Каждый заказ раскрывается в список операций (details) с датой и номером (ID).
    """
    from business.models import Deposit

    agg = {}  # client -> dict с суммами и details

    def slot(c):
        return agg.setdefault(c, {
            "revenue": ZERO, "advance": ZERO, "advance_supplier": ZERO,
            "cost": ZERO, "details": [],
        })

    def add_detail(c, date_, typ, amount, currency, ref):
        slot(c)["details"].append({
            "date": date_, "type": typ, "amount": amount,
            "amount_kgs": to_kgs(amount, currency), "currency": currency, "ref": ref,
        })

    dep = Deposit.objects.filter(account__module="BUSINESS").select_related("account")
    for d in _between(dep.filter(status=Deposit.Status.RECOGNIZED), date_from, date_to, "recognized_date"):
        c = _norm_client(d.source)
        slot(c)["revenue"] += to_kgs(d.amount, d.currency)
        add_detail(c, d.recognized_date or d.date, "Выручка (приход)", d.amount, d.currency, f"D-{d.id}")
    for d in _between(dep.filter(status=Deposit.Status.HELD), date_from, date_to, "date"):
        if str(d.source or "").startswith("Погашение"):
            continue
        c = _norm_client(d.source)
        slot(c)["advance"] += to_kgs(d.amount, d.currency)
        add_detail(c, d.date, "Аванс клиента", d.amount, d.currency, f"D-{d.id}")

    exp = Expense.objects.filter(account__module="BUSINESS").select_related("account")
    for e in _between(exp.filter(category=ExpenseCategory.COGS), date_from, date_to, "date"):
        c = _norm_client(e.description)
        slot(c)["cost"] += to_kgs(e.amount, e.account.currency)
        add_detail(c, e.date, "Закуп (себестоимость)", e.amount, e.account.currency, f"E-{e.id}")
    for e in _between(exp.filter(category=ExpenseCategory.SUPPLIER), date_from, date_to, "date"):
        c = _norm_client(e.description)
        if c == "—":
            continue
        slot(c)["advance_supplier"] += to_kgs(e.amount, e.account.currency)
        add_detail(c, e.date, "Аванс поставщику", e.amount, e.account.currency, f"E-{e.id}")

    orders = []
    for c, v in agg.items():
        margin = v["revenue"] - v["cost"]
        v["details"].sort(key=lambda d: str(d["date"]))
        orders.append({
            "client": c,
            "revenue": v["revenue"],
            "advance": v["advance"],
            "advance_supplier": v["advance_supplier"],
            "cost": v["cost"],
            "margin": margin,
            "margin_pct": _pct(margin, v["revenue"]),
            "status": _order_status(v["revenue"], v["advance"], v["cost"]),
            "details": v["details"],
        })
    orders.sort(key=lambda o: o["revenue"], reverse=True)

    totals = {
        "revenue": sum((o["revenue"] for o in orders), ZERO),
        "advance": sum((o["advance"] for o in orders), ZERO),
        "advance_supplier": sum((o["advance_supplier"] for o in orders), ZERO),
        "cost": sum((o["cost"] for o in orders), ZERO),
        "margin": sum((o["margin"] for o in orders), ZERO),
        "count": len(orders),
    }
    return {"orders": orders, "totals": totals}
