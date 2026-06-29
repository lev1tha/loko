"""Financial reporting engine for Loko (Express + Business).

Отчёты Локо (по документу-спецификации):
  * ОПиУ (P&L)  — по НАЧИСЛЕНИЮ, по «дате операции» (Sale.date / Expense.date).
  * ОДДС (Cash Flow) — пересказ ОПиУ по трём видам деятельности (операционная из
    ОПиУ; инвестиционная — приобретение ОС/ремонт/склад; финансовая — изъятие
    собственника + кредиты + выплата налога на прибыль). Остаток на начало — ручной
    перенос, конец = начало + чистый поток. См. build_cashflow.

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
    OPERATING_ARTICLES,
    INVESTING_ARTICLES,
    FINANCING_ARTICLES,
    kgs_of,
)

ZERO = Decimal("0.00")
ONE = Decimal("1")


def _rate() -> Decimal:
    return AppSettings.load().cny_to_kgs_rate


def to_kgs(amount: Decimal, currency: str, rate: Decimal | None = None) -> Decimal:
    """Перевод в сом. ``rate`` — снапшот-курс операции; если не задан, берётся
    текущий курс из Настроек (для случаев без зафиксированного курса)."""
    if currency == Currency.CNY and rate is None:
        rate = _rate()
    return kgs_of(amount, currency, rate)


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
    """Сумма в сомах по СНАПШОТ-курсам: группируем по (валюта, курс) и переводим."""
    total = ZERO
    for row in qs.values("account__currency", "kgs_rate").annotate(s=Sum(value_field)):
        total += kgs_of(row["s"] or ZERO, row["account__currency"], row["kgs_rate"])
    return total


def _expense_accrual(date_from, date_to, kinds, category=None, article=None, module=None):
    qs = _expense_qs(date_from, date_to, kinds, "date", category, article, module)
    return _sum_kgs(qs, "amount"), qs.count()


def _expense_paid(date_from, date_to, kinds, category=None, module=None, article=None):
    qs = _expense_qs(date_from, date_to, kinds, "payment_date", category, article, module)
    return _sum_kgs(qs, "paid_amount"), qs.count()


def _accrual_articles(date_from, date_to, kinds, category, article_set, module):
    """Разбивка по статьям внутри категории ПО НАЧИСЛЕНИЮ (для разделов ОДДС, который
    по документу-спецификации повторяет ОПиУ). Только ненулевые."""
    out = {}
    for art in OpexArticle:
        if art not in article_set:
            continue
        amt, cnt = _expense_accrual(date_from, date_to, kinds, category, art.value, module)
        if amt:
            out[art.value] = {"label": art.label, "amount": amt, "count": cnt}
    return out


# ---------------------------------------------------------------------------
# Deposits (Business)
# ---------------------------------------------------------------------------
def _recognized_deposits(date_from, date_to, kinds, module=None):
    from business.models import Deposit

    qs = _by_module(
        Deposit.objects.filter(status=Deposit.Status.RECOGNIZED, account__kind__in=kinds), module
    )
    qs = _between(qs, date_from, date_to, "recognized_date")
    total = ZERO
    for row in qs.values("currency", "kgs_rate").annotate(s=Sum("amount")):
        total += kgs_of(row["s"] or ZERO, row["currency"], row["kgs_rate"])
    return total, qs.count()


def _other_income(date_from, date_to, kinds, module=None):
    """Прочий доход (OtherIncome) в сомах по снапшот-курсу. Входит в выручку без 55%."""
    from .models import OtherIncome

    qs = _by_module(OtherIncome.objects.filter(account__kind__in=kinds), module)
    qs = _between(qs, date_from, date_to, "date")
    total = ZERO
    for row in qs.values("account__currency", "kgs_rate").annotate(s=Sum("amount")):
        total += kgs_of(row["s"] or ZERO, row["account__currency"], row["kgs_rate"])
    return total, qs.count()


def _opex_breakdown(date_from, date_to, kinds, module=None):
    articles = {}
    total = ZERO
    count = 0
    for art in (a for a in OpexArticle if a in OPERATING_ARTICLES):
        amount, cnt = _expense_accrual(date_from, date_to, kinds, ExpenseCategory.OPEX, art.value, module)
        articles[art.value] = {"label": art.label, "amount": amount, "count": cnt}
        total += amount
        count += cnt
    return {"articles": articles, "total": total, "count": count}


# ===========================================================================
# ОПиУ (P&L) — по начислению
# ===========================================================================
def _pnl_base(date_from, date_to, payment, module):
    """Компоненты ОПиУ до строки налога (для заданного канала оплаты)."""
    kinds = _kinds_for_payment(payment)
    sales = _sales(date_from, date_to, kinds, "date", module)
    express_revenue = sales.aggregate(s=Sum("price_som"))["s"] or ZERO
    deposit_revenue, deposit_count = _recognized_deposits(date_from, date_to, kinds, module)
    other_income, other_income_count = _other_income(date_from, date_to, kinds, module)
    revenue = express_revenue + deposit_revenue + other_income

    # Себестоимость: Express — расчётная (% от выручки, по документу-спецификации;
    # заменяет фактические карго-оттоки, которые живут в ОДДС/кассе). Business —
    # фактический закуп товара (реальные COGS-расходы, сверка с Excel сохраняется).
    cfg = AppSettings.load()
    express_cogs = (express_revenue * cfg.express_cogs_pct / Decimal("100")).quantize(ZERO)
    business_cogs = (ZERO if module == "EXPRESS"
                     else _expense_accrual(date_from, date_to, kinds, ExpenseCategory.COGS, module="BUSINESS")[0])
    cogs = express_cogs + business_cogs
    gross_profit = revenue - cogs

    opex = _opex_breakdown(date_from, date_to, kinds, module)
    operating_profit = gross_profit - opex["total"]

    other_expenses, other_count = _expense_accrual(date_from, date_to, kinds, ExpenseCategory.OTHER, module=module)
    financial_expenses = ZERO    # задел: финансовые расходы
    # Прочий доход уже включён в выручку (формирует валовую/операционную прибыль),
    # повторно на уровне ПДН не добавляем.
    pre_tax_profit = operating_profit - other_expenses - financial_expenses
    return {
        "sales": sales, "express_revenue": express_revenue, "deposit_revenue": deposit_revenue,
        "deposit_count": deposit_count, "revenue": revenue, "cogs": cogs, "gross_profit": gross_profit,
        "opex": opex, "operating_profit": operating_profit, "other_expenses": other_expenses,
        "other_count": other_count, "other_income": other_income, "other_income_count": other_income_count,
        "financial_expenses": financial_expenses, "pre_tax_profit": pre_tax_profit,
    }


def build_pnl(date_from=None, date_to=None, payment="all", tax_rate=None, module=None):
    """ОПиУ. Налог на «прибыль до налогов» по ставке канала оплаты:
    наличные cash_tax_rate (6%), безнал noncash_tax_rate (4%) — оба редактируемы.
    Для payment='all' каждый канал облагается своей ставкой и суммируется.
    ?tax_rate= — ручной плоский override (для сценария «что если»).
    """
    cfg = AppSettings.load()
    cash_rate = cfg.cash_tax_rate
    noncash_rate = cfg.noncash_tax_rate
    single_pct = cfg.single_tax_pct

    base = _pnl_base(date_from, date_to, payment, module)
    pre = base["pre_tax_profit"]

    # Express — «единый налог» = % от ВЫРУЧКИ Express (документ-спецификация).
    express_tax = (base["express_revenue"] * single_pct / Decimal("100")).quantize(ZERO)

    if tax_rate is not None and str(tax_rate) != "":
        # Ручной плоский override на всю прибыль до налога (сценарий «что если»).
        rate = Decimal(str(tax_rate))
        tax = (max(pre, ZERO) * rate / Decimal("100")).quantize(ZERO)
        express_tax = business_tax = ZERO
        eff_rate = rate
    else:
        # Business — налог по каналу оплаты на прибыль Business (как раньше).
        def _btax(pay):
            if module == "EXPRESS":
                return ZERO
            bpre = _pnl_base(date_from, date_to, pay, "BUSINESS")["pre_tax_profit"]
            rate = cash_rate if pay == "cash" else noncash_rate
            return (max(bpre, ZERO) * rate / Decimal("100")).quantize(ZERO)

        business_tax = _btax(payment) if payment in ("cash", "noncash") else _btax("cash") + _btax("noncash")
        tax = express_tax + business_tax
        eff_rate = _pct(tax, max(pre, ZERO)) if pre > ZERO else ZERO

    net_profit = pre - tax
    opex, sales, revenue = base["opex"], base["sales"], base["revenue"]
    return {
        "report": "PNL",
        "period": {"from": date_from, "to": date_to},
        "payment": payment,
        "express_revenue": base["express_revenue"],
        "deposit_revenue": base["deposit_revenue"],
        "revenue": revenue,
        "cogs": base["cogs"],
        "gross_profit": base["gross_profit"],
        "gross_margin_pct": _pct(base["gross_profit"], revenue),
        "opex_articles": opex["articles"],
        "operating_expenses": opex["total"],
        "operating_profit": base["operating_profit"],
        "other_income": base["other_income"],
        "other_expenses": base["other_expenses"],
        "financial_expenses": base["financial_expenses"],
        "pre_tax_profit": pre,
        "tax_rate": eff_rate,
        "cash_tax_rate": cash_rate,
        "noncash_tax_rate": noncash_rate,
        "single_tax_pct": single_pct,
        "express_cogs_pct": cfg.express_cogs_pct,
        "express_tax": express_tax,
        "business_tax": business_tax,
        "tax": tax,
        "net_profit": net_profit,
        "net_margin_pct": _pct(net_profit, revenue),
        "sales_count": sales.count(),
        "deposit_count": base["deposit_count"],
        "opex_count": opex["count"],
        "operations": {"income": sales.count() + base["deposit_count"], "expense": opex["count"] + base["other_count"]},
    }


# ===========================================================================
# Cash helpers for opening / closing balances (consolidated KGS)
# ===========================================================================
def _consolidated_cash(upper_date, inclusive, module=None, kinds=None):
    """Consolidated KGS cash counting flows up to a boundary date.

    inclusive=True → flows with date <= upper_date (closing).
    inclusive=False → flows with date <  upper_date (opening).
    ``kinds`` — фильтр по типу счёта (нал/безнал), чтобы при выборе канала
    оплаты в ОДДС opening/closing считались по тем же счетам, что и потоки.
    Каждая CNY-компонента переводится в сом по своему снапшот-курсу.
    """
    op = "lte" if inclusive else "lt"

    def filt(qs, field):
        if upper_date is None:
            return qs if inclusive else qs.none()
        return qs.filter(**{f"{field}__{op}": upper_date})

    total = ZERO
    accounts = Account.objects.all()
    if module:
        accounts = accounts.filter(module=module)
    if kinds:
        accounts = accounts.filter(kind__in=kinds)
    for acc in accounts:
        cny = acc.currency == Currency.CNY
        total += acc.initial_balance * (acc.initial_kgs_rate or ONE) if cny else acc.initial_balance
        # Продажи (Express) всегда в сомах.
        total += filt(acc.sales, "payment_date").aggregate(s=Sum("paid_som"))["s"] or ZERO
        # Прочий доход — по снапшот-курсу счёта.
        for g in filt(acc.other_incomes, "date").values("kgs_rate").annotate(s=Sum("amount")):
            total += kgs_of(g["s"] or ZERO, acc.currency, g["kgs_rate"])
        # Депозиты и расходы — по снапшот-курсу (группировка по курсу).
        for g in filt(acc.deposits, "date").values("currency", "kgs_rate").annotate(s=Sum("amount")):
            total += kgs_of(g["s"] or ZERO, g["currency"], g["kgs_rate"])
        for g in (
            filt(acc.expenses, "payment_date")
            .values("account__currency", "kgs_rate")
            .annotate(s=Sum("paid_amount"))
        ):
            total -= kgs_of(g["s"] or ZERO, g["account__currency"], g["kgs_rate"])
        # Переводы: каждая нога по снапшот-курсу своей стороны (kgs_in/kgs_out).
        for t in filt(acc.incoming_transfers, "date").select_related("to_account", "from_account"):
            total += t.kgs_in
        for t in filt(acc.outgoing_transfers, "date").select_related("to_account", "from_account"):
            total -= t.kgs_out
    return total


# ===========================================================================
# ОДДС (Cash Flow) — пересказ ОПиУ по видам деятельности (документ-спецификация)
# ===========================================================================
def build_cashflow(date_from=None, date_to=None, payment="all", module=None, opening_override=None):
    """ОДДС по документу-спецификации: пересказ ОПиУ по трём видам деятельности
    (а НЕ кассовый отчёт по оплате). Решение пользователя 2026-06-29 — операционный
    раздел берёт цифры из ОПиУ, налог на прибыль показан в финансовой деятельности.

    Формула (как в образце документа): Итого опер. + Итого инвест. + Итого фин.
    = чистый поток; конец = начало (ручной/перенос) + чистый поток.
    """
    kinds = _kinds_for_payment(payment)

    # --- Операционная деятельность: берётся из ОПиУ ------------------------
    pnl = build_pnl(date_from, date_to, payment, module=module)
    revenue = pnl["revenue"]                  # «Денежные потоки от деятельности»
    cogs = pnl["cogs"]                        # «Расходы на себестоимость продукции» (55%)
    operating_expenses = pnl["operating_expenses"]
    net_operating = pnl["operating_profit"]   # = выручка − себест − опер.расходы
    profit_tax = pnl["tax"]                   # «Выплата налога на прибыль» (фин. деят.)

    # --- Инвестиционная деятельность (приобретение ОС/ремонт/склад) --------
    invest_total, inv_cnt = _expense_accrual(date_from, date_to, kinds, ExpenseCategory.INVEST, module=module)
    investing_articles = _accrual_articles(date_from, date_to, kinds, ExpenseCategory.INVEST, INVESTING_ARTICLES, module)
    net_investing = -invest_total

    # --- Финансовая деятельность (изъятие собственника + кредиты + налог) --
    owner, owner_cnt = _expense_accrual(date_from, date_to, kinds, ExpenseCategory.OWNER, module=module)
    financing_exp, fin_cnt = _expense_accrual(date_from, date_to, kinds, ExpenseCategory.FINANCING, module=module)
    financing_articles = _accrual_articles(date_from, date_to, kinds, ExpenseCategory.FINANCING, FINANCING_ARTICLES, module)
    financing_outflow = owner + financing_exp + profit_tax
    net_financing = -financing_outflow

    net_cash_flow = net_operating + net_investing + net_financing

    # Остаток на начало: вручную (перенос «чистого потока прошлого месяца») либо
    # авто из истории. Конец = начало + чистый поток (формула документа).
    if opening_override is not None:
        opening = opening_override
    else:
        opening = _consolidated_cash(date_from, inclusive=False, module=module, kinds=kinds)
    closing = opening + net_cash_flow

    expense_count = pnl["opex_count"] + inv_cnt + owner_cnt + fin_cnt

    return {
        "report": "CASHFLOW",
        "period": {"from": date_from, "to": date_to},
        "payment": payment,
        "opening_balance": opening,
        "opening_manual": opening_override is not None,
        # Операционная (из ОПиУ)
        "operating_inflow": revenue,
        "cogs": cogs,
        "operating_expenses": operating_expenses,
        "net_operating": net_operating,
        # Инвестиционная
        "investing_outflow": invest_total,
        "net_investing": net_investing,
        "investing_articles": investing_articles,
        # Финансовая
        "owner_withdrawals": owner,
        "financing_other": financing_exp,
        "profit_tax": profit_tax,
        "financing_outflow": financing_outflow,
        "net_financing": net_financing,
        "financing_articles": financing_articles,
        "net_cash_flow": net_cash_flow,
        "closing_balance": closing,
        "payment_breakdown": _payment_breakdown(date_from, date_to, module),
        "operations": {"income": pnl["operations"]["income"], "expense": expense_count},
    }


def build_monthly(date_from=None, date_to=None, module=None, report="pnl"):
    """Помесячная разбивка отчёта (месяцы периода = колонки). Каждый месяц считается
    отдельным вызовом build_pnl/build_cashflow — как просит документ («на каждый месяц»)."""
    from datetime import date as _date
    import calendar
    from dateutil.relativedelta import relativedelta

    def _to_date(v):
        if isinstance(v, _date):
            return v
        return _date.fromisoformat(str(v)) if v else None

    df, dtt = _to_date(date_from), _to_date(date_to)
    months = []
    if df and dtt and df <= dtt:
        cur = df.replace(day=1)
        while cur <= dtt:
            last = cur.replace(day=calendar.monthrange(cur.year, cur.month)[1])
            m_from, m_to = max(cur, df), min(last, dtt)
            if report == "cashflow":
                d = build_cashflow(m_from, m_to, module=module)
                months.append({
                    "month": cur.strftime("%Y-%m"),
                    "operating_inflow": d["operating_inflow"], "net_operating": d["net_operating"],
                    "net_investing": d["net_investing"], "net_financing": d["net_financing"],
                    "net_cash_flow": d["net_cash_flow"],
                    "opening_balance": d["opening_balance"], "closing_balance": d["closing_balance"],
                })
            else:
                d = build_pnl(m_from, m_to, module=module)
                months.append({
                    "month": cur.strftime("%Y-%m"),
                    "revenue": d["revenue"], "cogs": d["cogs"], "gross_profit": d["gross_profit"],
                    "operating_expenses": d["operating_expenses"], "pre_tax_profit": d["pre_tax_profit"],
                    "tax": d["tax"], "net_profit": d["net_profit"],
                })
            cur = cur + relativedelta(months=1)
    return {"report": report, "module": module, "months": months}


def _payment_breakdown(date_from, date_to, module=None):
    """Свод оплат: приход/расход по каждому счёту (методу), в KGS, по оплате."""
    rows = []
    accounts = Account.objects.filter(module=module) if module else Account.objects.all()
    for acc in accounts:
        sales_in = _between(acc.sales.all(), date_from, date_to, "payment_date")
        dep_in = _between(acc.deposits.all(), date_from, date_to, "date")
        exp_out = _between(acc.expenses.all(), date_from, date_to, "payment_date")
        sales_paid = sales_in.aggregate(s=Sum("paid_som"))["s"] or ZERO
        dep_native = dep_in.aggregate(s=Sum("amount"))["s"] or ZERO
        income = sales_paid + dep_native        # в валюте счёта (для отображения)
        expense = exp_out.aggregate(s=Sum("paid_amount"))["s"] or ZERO
        # Сомовые эквиваленты — по снапшот-курсам (продажи всегда в сомах).
        income_kgs = sales_paid + sum(
            (kgs_of(g["s"] or ZERO, g["currency"], g["kgs_rate"])
             for g in dep_in.values("currency", "kgs_rate").annotate(s=Sum("amount"))),
            ZERO,
        )
        expense_kgs = sum(
            (kgs_of(g["s"] or ZERO, g["account__currency"], g["kgs_rate"])
             for g in exp_out.values("account__currency", "kgs_rate").annotate(s=Sum("paid_amount"))),
            ZERO,
        )
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
                    "income_kgs": income_kgs,
                    "expense_kgs": expense_kgs,
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
                "current_balance_kgs": acc.balance_kgs,
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
            .values("currency", "kgs_rate")
            .annotate(s=Sum("amount"))
        )
        biz[kind.value] = sum((kgs_of(r["s"] or ZERO, r["currency"], r["kgs_rate"]) for r in rows), ZERO)

    # Express receivable = неоплаченная часть продаж Express (начисление − оплата).
    s = Sale.objects.filter(account__module="EXPRESS").aggregate(a=Sum("price_som"), p=Sum("paid_som"))
    express_receivable = (s["a"] or ZERO) - (s["p"] or ZERO)

    # Кредиторка по расходам — РАЗДЕЛЬНО по направлению (не валим всё в Express).
    def _exp_payable(mod):
        rows = (
            Expense.objects.filter(account__module=mod)
            .values("account__currency", "kgs_rate")
            .annotate(a=Sum("amount"), p=Sum("paid_amount"))
        )
        return sum(
            (kgs_of((r["a"] or ZERO) - (r["p"] or ZERO), r["account__currency"], r["kgs_rate"]) for r in rows),
            ZERO,
        )

    express_payable = _exp_payable("EXPRESS")
    business_exp_payable = _exp_payable("BUSINESS")

    business_payable = biz.get(Debt.Kind.PAYABLE, ZERO) + business_exp_payable
    payable = business_payable + express_payable
    receivable = biz.get(Debt.Kind.RECEIVABLE, ZERO) + express_receivable
    return {
        "payable": payable,
        "receivable": receivable,
        "net": receivable - payable,
        "business_payable": business_payable,
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

    def add_detail(c, date_, typ, amount, currency, ref, amount_kgs):
        slot(c)["details"].append({
            "date": date_, "type": typ, "amount": amount,
            "amount_kgs": amount_kgs, "currency": currency, "ref": ref,
        })

    dep = Deposit.objects.filter(account__module="BUSINESS").select_related("account")
    for d in _between(dep.filter(status=Deposit.Status.RECOGNIZED), date_from, date_to, "recognized_date"):
        c = _norm_client(d.source)
        slot(c)["revenue"] += d.kgs_value
        add_detail(c, d.recognized_date or d.date, "Выручка (приход)", d.amount, d.currency, f"D-{d.id}", d.kgs_value)
    for d in _between(dep.filter(status=Deposit.Status.HELD), date_from, date_to, "date"):
        if str(d.source or "").startswith("Погашение"):
            continue
        c = _norm_client(d.source)
        slot(c)["advance"] += d.kgs_value
        add_detail(c, d.date, "Аванс клиента", d.amount, d.currency, f"D-{d.id}", d.kgs_value)

    exp = Expense.objects.filter(account__module="BUSINESS").select_related("account")
    for e in _between(exp.filter(category=ExpenseCategory.COGS), date_from, date_to, "date"):
        c = _norm_client(e.description)
        slot(c)["cost"] += e.kgs_amount
        add_detail(c, e.date, "Закуп (себестоимость)", e.amount, e.account.currency, f"E-{e.id}", e.kgs_amount)
    for e in _between(exp.filter(category=ExpenseCategory.SUPPLIER), date_from, date_to, "date"):
        c = _norm_client(e.description)
        if c == "—":
            continue
        slot(c)["advance_supplier"] += e.kgs_amount
        add_detail(c, e.date, "Аванс поставщику", e.amount, e.account.currency, f"E-{e.id}", e.kgs_amount)

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


# ===========================================================================
# Журнал ВСЕХ операций (Express + Business) — «как сложились цифры» (доказательство)
# ===========================================================================
_JOURNAL_PAGE = 500   # размер страницы по умолчанию
_JOURNAL_MAX = 2000   # максимум строк за один запрос (защита); итоги — по ВСЕМ операциям


def journal(date_from=None, date_to=None, module=None, effect_filter=None, limit=None, offset=0):
    """Единый хронологический журнал всех операций с фильтром по направлению:
      * Express — продажи (Sale) + расходы карго (Expense).
      * Business — приходы/авансы/погашения (Deposit), закуп/аванс/изъятие/прочее
        (Expense), переводы и конвертации (Transfer).
    Плюс свод — как из этих событий вышли цифры дашборда. Для сверки с Excel.
    module: None (всё) | "EXPRESS" | "BUSINESS".
    """
    from business.models import Deposit
    from express.models import Sale
    from .models import OtherIncome, Transfer

    want = lambda m: module is None or module == m
    ops = []

    def add(date_, typ, party, account, amount, currency, flow, effect, ref, mod, amount_kgs=None):
        amount = amount or ZERO
        ak = amount if amount_kgs is None else amount_kgs
        ops.append({
            "date": date_, "type": typ, "party": party, "account": account,
            "amount": amount, "currency": currency,
            "amount_kgs": (ak or ZERO).quantize(ZERO),
            "flow": flow, "effect": effect, "ref": ref, "module": mod,
        })

    # Продажи Express → выручка (+ динамическая себестоимость, если задана) —
    # себестоимость живёт на самой продаже (Sale.cost_som), а не отдельным расходом.
    if want("EXPRESS"):
        sales = Sale.objects.filter(account__module="EXPRESS").select_related("account")
        for s in _between(sales, date_from, date_to, "date"):
            add(s.date, "Продажа Express", s.client_code, s.account.name, s.price_som, "KGS", "in", "Выручка", f"S-{s.id}", "EXPRESS")
            if s.cost_som and s.cost_som > 0:
                add(s.date, "Себестоимость карго", s.client_code, s.account.name, s.cost_som, "KGS", "out", "Себестоимость", f"SC-{s.id}", "EXPRESS")

    # Депозиты Business: признанная выручка — по дате признания (как build_pnl),
    # авансы и погашения — по дате получения. Сумма в сомах — по снапшот-курсу.
    if want("BUSINESS"):
        dep = Deposit.objects.filter(account__module="BUSINESS").select_related("account")
        for d in _between(dep.filter(status=Deposit.Status.RECOGNIZED), date_from, date_to, "recognized_date"):
            add(d.recognized_date or d.date, "Приход клиента", _norm_client(d.source), d.account.name, d.amount, d.currency, "in", "Выручка", f"D-{d.id}", "BUSINESS", d.kgs_value)
        for d in _between(dep.exclude(status=Deposit.Status.RECOGNIZED), date_from, date_to, "date"):
            src = str(d.source or "")
            typ, effect = ("Погашение долга", "Не влияет на прибыль") if src.startswith("Погашение") else ("Аванс клиента", "Аванс (не выручка)")
            add(d.date, typ, _norm_client(d.source), d.account.name, d.amount, d.currency, "in", effect, f"D-{d.id}", "BUSINESS", d.kgs_value)

    # Расходы (по направлению): закуп / опер / аванс поставщику / изъятие / прочее
    EXP_MAP = {
        ExpenseCategory.COGS: ("Закуп товара", "Себестоимость"),
        ExpenseCategory.OPEX: ("Операционный расход", "Опер. расход"),
        ExpenseCategory.SUPPLIER: ("Оплата/аванс поставщику", "Аванс (не расход)"),
        ExpenseCategory.OWNER: ("Изъятие собственника", "Вывод (не расход)"),
        ExpenseCategory.OTHER: ("Прочий расход", "Прочее"),
        ExpenseCategory.INVEST: ("Покупка оборудования", "Инвестиции"),
        ExpenseCategory.FINANCING: ("Кредит/проценты", "Финансовое"),
    }
    exp = Expense.objects.select_related("account")
    if module:
        exp = exp.filter(account__module=module)
    for e in _between(exp, date_from, date_to, "date"):
        typ, effect = EXP_MAP.get(e.category, ("Расход", "Прочее"))
        # Express: себестоимость в ОПиУ — расчётная (% от выручки), а фактические
        # карго-оттоки показываем как кассовое движение (в прибыль ОПиУ не входят).
        if e.category == ExpenseCategory.COGS and e.account.module == "EXPRESS":
            typ, effect = "Карго-оплата (касса)", "Себестоимость (касса)"
        add(e.date, typ, e.description or typ, e.account.name, e.amount, e.account.currency, "out", effect, f"E-{e.id}", e.account.module, e.kgs_amount)

    # Express: расчётная себестоимость (% от выручки, как в ОПиУ) — одной строкой,
    # чтобы журнал сходился с дашбордом по прибыли.
    if want("EXPRESS"):
        cfg = AppSettings.load()
        exp_rev = sum((o["amount_kgs"] for o in ops if o["module"] == "EXPRESS" and o["effect"] == "Выручка"), ZERO)
        cogs55 = (exp_rev * cfg.express_cogs_pct / Decimal("100")).quantize(ZERO)
        if cogs55 > 0:
            add(date_to, "Себестоимость карго (расчётная)", f"{cfg.express_cogs_pct}% от выручки", "—",
                cogs55, "KGS", "out", "Себестоимость", "COGS-55", "EXPRESS")

    # Прочий доход — входит в выручку (без расчётной себестоимости 55%).
    oi = OtherIncome.objects.select_related("account")
    if module:
        oi = oi.filter(account__module=module)
    for o in _between(oi, date_from, date_to, "date"):
        add(o.date, "Прочий доход", o.description or "Прочий доход", o.account.name,
            o.amount, o.account.currency, "in", "Прочий доход", f"OI-{o.id}", o.account.module, o.kgs_amount)

    # Переводы и конвертации (по направлению счёта-источника)
    tr = Transfer.objects.select_related("from_account", "to_account")
    if module:
        tr = tr.filter(from_account__module=module)
    for t in _between(tr, date_from, date_to, "date"):
        typ = "Покупка юаня (обмен)" if t.is_conversion else "Внутренний перевод"
        party = f"{t.from_account.name} → {t.to_account.name}"
        add(t.date, typ, party, t.from_account.name, t.amount, t.from_account.currency, "move", "Перемещение", f"T-{t.id}", t.from_account.module, t.kgs_out)

    ops.sort(key=lambda o: (str(o["date"]), o["ref"]), reverse=True)

    def by_effect(eff):
        return sum((o["amount_kgs"] for o in ops if o["effect"] == eff), ZERO)

    revenue = by_effect("Выручка") + by_effect("Прочий доход")
    cogs = by_effect("Себестоимость")
    opex = by_effect("Опер. расход")
    other = by_effect("Прочее")  # неоперационные расходы — тоже уменьшают прибыль (как в build_pnl)
    total_count = len(ops)
    totals = {
        "revenue": revenue,
        "cogs": cogs,
        "opex": opex,
        "other_expenses": other,
        "pre_tax_profit": revenue - cogs - opex - other,
        # справочно — не влияют на прибыль
        "advance_client": by_effect("Аванс (не выручка)"),
        "advance_supplier": by_effect("Аванс (не расход)"),
        "owner": by_effect("Вывод (не расход)"),
        "repayment": by_effect("Не влияет на прибыль"),
        "count": total_count,
    }

    # Фильтр таблицы по «эффекту» (клик по плитке) + пагинация. Плитки-итоги выше —
    # всегда по ВСЕМ операциям периода и от страницы/фильтра не зависят.
    rows = [o for o in ops if o["effect"] == effect_filter] if effect_filter else ops
    count = len(rows)
    filtered_sum = sum((o["amount_kgs"] for o in rows), ZERO)
    page_size = _JOURNAL_PAGE if limit is None else max(1, min(int(limit), _JOURNAL_MAX))
    offset = max(0, int(offset or 0))
    page = rows[offset:offset + page_size]
    return {
        "operations": page,
        "count": count,                 # строк, попавших под текущий фильтр/период
        "total_count": total_count,     # всего операций за период (без фильтра)
        "offset": offset,
        "limit": page_size,
        "shown": len(page),
        "filtered_sum": filtered_sum.quantize(ZERO),
        "totals": totals,
    }


# ===========================================================================
# Детальная расшифровка строки отчёта — «откуда деньги»
# ===========================================================================
BREAKDOWN_LABELS = {
    "revenue": "Выручка",
    "express_revenue": "Продажи Loko Express",
    "deposit_revenue": "Депозиты, признанные как выручка",
    "cogs": "Себестоимость",
    "opex": "Операционные расходы",
    "other": "Прочие / неоперационные расходы",
    "supplier": "Оплата / аванс поставщикам",
    "owner": "Изъятие собственника",
    "invest": "Инвестиции (оборудование/активы)",
    "financing": "Финансовые (кредиты/проценты)",
    "inflow": "Приток денежных средств",
    "outflow": "Отток денежных средств",
}


def breakdown(line, date_from=None, date_to=None, payment="all", module=None, basis="accrual"):
    """Список операций, из которых сложилась строка отчёта.

    basis: 'accrual' (ОПиУ, по дате операции/начислению) | 'cash' (ОДДС, по дате оплаты/оплате).
    line:  revenue | express_revenue | deposit_revenue | cogs | opex | opex_<ARTICLE> |
           other | supplier | owner | inflow | outflow
    """
    from express.models import Sale
    from business.models import Deposit

    kinds = _kinds_for_payment(payment)
    cash = basis == "cash"
    sale_date = "payment_date" if cash else "date"
    sale_amt = "paid_som" if cash else "price_som"
    exp_date = "payment_date" if cash else "date"
    exp_amt = "paid_amount" if cash else "amount"
    items = []

    def sale_items(value_field=sale_amt):
        qs = _by_module(Sale.objects.filter(account__kind__in=kinds), module).select_related("account")
        for s in _between(qs, date_from, date_to, sale_date).order_by("-" + sale_date):
            amt = getattr(s, value_field)
            if not amt:
                continue
            items.append({
                "id": f"S-{s.id}", "date": getattr(s, sale_date) or s.date,
                "title": f"Продажа · {s.client_code}", "account": s.account.name,
                "amount": amt, "currency": "KGS", "amount_kgs": amt,
            })

    def deposit_items(recognized):
        qs = Deposit.objects.filter(account__module="BUSINESS")
        qs = qs.filter(status=Deposit.Status.RECOGNIZED) if recognized else qs
        field = "recognized_date" if recognized else "date"
        for d in _between(_by_module(qs, module), date_from, date_to, field).select_related("account"):
            items.append({
                "id": f"D-{d.id}", "date": getattr(d, field) or d.date,
                "title": f"Депозит · {d.source}", "account": d.account.name,
                "amount": d.amount, "currency": d.currency, "amount_kgs": d.kgs_value,
            })

    def expense_items(category=None, article=None):
        qs = _expense_qs(date_from, date_to, kinds, exp_date, category, article, module)
        for e in qs.select_related("account").order_by("-" + exp_date):
            amt = getattr(e, exp_amt)
            if not amt:
                continue
            label = e.get_opex_article_display() if e.opex_article else e.get_category_display()
            title = e.description or label
            items.append({
                "id": f"E-{e.id}", "date": getattr(e, exp_date) or e.date,
                "title": title, "account": e.account.name,
                "amount": amt, "currency": e.account.currency,
                "amount_kgs": kgs_of(amt, e.account.currency, e.kgs_rate),
            })

    if line in ("revenue", "express_revenue", "inflow"):
        sale_items()
    if line in ("revenue", "deposit_revenue", "inflow"):
        deposit_items(recognized=not cash)
    if line == "cogs":
        # Себестоимость карго (Sale.cost_som) — только по начислению: у неё нет даты
        # оплаты, поэтому в кассовом разрезе ОДДС строка = только COGS-расходы.
        if not cash:
            sale_items(value_field="cost_som")
        expense_items(category=ExpenseCategory.COGS)
    if line == "opex":
        expense_items(category=ExpenseCategory.OPEX)
    if line.startswith("opex_"):
        expense_items(category=ExpenseCategory.OPEX, article=line.split("_", 1)[1])
    if line in ("other", "outflow"):
        expense_items(category=ExpenseCategory.OTHER)
    if line in ("supplier", "outflow"):
        expense_items(category=ExpenseCategory.SUPPLIER)
    if line in ("owner", "outflow"):
        expense_items(category=ExpenseCategory.OWNER)
    if line in ("invest", "outflow"):
        expense_items(category=ExpenseCategory.INVEST)
    if line in ("financing", "outflow"):
        expense_items(category=ExpenseCategory.FINANCING)
    if line == "outflow":
        expense_items(category=ExpenseCategory.OPEX)
        expense_items(category=ExpenseCategory.COGS)

    items.sort(key=lambda i: str(i["date"]), reverse=True)
    total = sum((i["amount_kgs"] for i in items), ZERO)  # точный итог по ВСЕМ операциям
    count = len(items)
    CAP = 500
    return {
        "line": line,
        "label": BREAKDOWN_LABELS.get(line, line),
        "basis": basis,
        "total": total,
        "count": count,
        "shown": min(count, CAP),
        "truncated": count > CAP,
        "items": items[:CAP],
    }
