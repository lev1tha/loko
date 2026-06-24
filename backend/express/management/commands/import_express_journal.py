"""Импорт Loko Express из единого журнала «Финансовый учет карго компании Локо1.xlsx».

Особенности файла (доделываем то, что формулы Excel не посчитали — «940 ошибок»):
  * Реальная сумма операции — в колонке «Сумма в сомах» (формульные «Сумма
    начисления/оплаты» пустые).
  * «?» в суммах («4399?») — оператор не уверен в сумме: берём числовую часть.
  * «?» в коде клиента («?313») — сохраняем как есть (метка неуточнённого клиента).
  * Битая дата «16.06.20226» → 2026-06-16.
  * «Метод оплаты» почти везде пуст → счёт «Банк не указан».

Маппинг по «Тип операции»:
  Поступление / Приход / Не заплатил → Sale (DIRECT). «Не заплатил» → оплата 0 (дебиторка).
  Расход → Expense. По «Вид операции/статья»: себестоимость/закуп/склад/таможня → COGS, иначе OpEx.
"""

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from finance.models import Account, AppSettings, Currency, Expense, ExpenseCategory, Module, OpexArticle
from express.models import Sale

DEFAULT_PATH = str(Path.home() / "Downloads" / "Финансовы̆ учет карго компании Локо1.xlsx")
# (имя файла с диакритикой — задаём через --path при необходимости)

SHEET = "4. Журнал операций"
HEADER_ROW = 5
C_DATE_OP, C_DATE_PAY, C_TYPE, C_KIND = 1, 2, 5, 6
C_CLIENT, C_METHOD, C_SUM_SOM = 13, 32, 35

INCOME_TYPES = {"Поступление", "Приход", "Не заплатил"}
COGS_HINTS = ("себестоим", "закуп", "склад", "таможен", "перевоз", "доставк")


def is_uncertain(value):
    return isinstance(value, str) and ("?" in value or "/" in value)


def clean_amount(value):
    """Берём ПЕРВОЕ число из значения:
    '4399?' → 4399 ; '1433/1400' → 1433 (диапазон) ; '12 345,50' → 12345.5 ; '' → 0."""
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        s = value.split("/")[0]                       # диапазон «1433/1400» → первое
        s = s.replace("?", "").replace("\xa0", " ")
        s = re.sub(r"(?<=\d)[ ](?=\d)", "", s)        # пробел-разделитель тысяч
        m = re.search(r"-?\d+(?:[.,]\d+)?", s)
        if not m:
            return Decimal("0")
        try:
            return Decimal(m.group(0).replace(",", "."))
        except Exception:
            return Decimal("0")
    return Decimal("0")


def parse_date(value, fallback=None):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        m = re.match(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,6})", value.strip())
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if y > 2100:               # «20226» → 2026
                y = int(str(y)[:4]) if len(str(y)) >= 4 else 2026
                if y > 2100:
                    y = 2026
            if y < 100:
                y += 2000
            try:
                return date(y, mo, d)
            except ValueError:
                return fallback
    return fallback


def method_account(method, accounts):
    m = (str(method) if method else "").strip().lower()
    if "оптима" in m:
        return accounts["Оптима Банк"]
    if "мбанк" in m or m == "мб":
        return accounts["МБанк"]
    if "налич" in m:
        return accounts["Наличные"]
    return accounts["Банк не указан"]


class Command(BaseCommand):
    help = "Импорт Express из журнала «…Локо1.xlsx» (с очисткой «?» и битых дат)."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=DEFAULT_PATH)

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            import openpyxl
        except ImportError:
            raise CommandError("pip install openpyxl")

        path = options["path"]
        if not Path(path).exists():
            raise CommandError(f"Файл не найден:\n{path}\nУкажите --path")

        cfg = AppSettings.load()
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb[SHEET]

        names = ["Наличные", "Оптима Банк", "МБанк", "Банк не указан"]
        accounts = {}
        for name in names:
            accounts[name], _ = Account.objects.get_or_create(
                name=name,
                defaults={
                    "kind": Account.Kind.CASH if name == "Наличные" else Account.Kind.BANK,
                    "currency": Currency.KGS,
                    "module": Module.EXPRESS,
                },
            )
        acc_ids = [a.id for a in accounts.values()]
        Sale.objects.filter(account_id__in=acc_ids).delete()
        Expense.objects.filter(account_id__in=acc_ids).delete()

        snap = dict(price_per_kg_usd=cfg.price_per_kg_usd, usd_rate_som=cfg.usd_rate_som,
                    cost_per_kg_som=cfg.base_cost_per_kg_som)

        sales, expenses = [], []
        stats = {"income": 0, "expense": 0, "unpaid": 0, "q_amount": 0, "q_client": 0,
                 "bad_date": 0, "skipped": 0}

        for r in ws.iter_rows(min_row=HEADER_ROW + 1, values_only=True):
            if r[0] is None:
                continue
            op_type = str(r[C_TYPE] or "").strip()
            raw_sum = r[C_SUM_SOM]
            amount = clean_amount(raw_sum)
            uncertain = is_uncertain(raw_sum)
            if uncertain:
                stats["q_amount"] += 1
            client = r[C_CLIENT]
            if isinstance(client, str) and "?" in client:
                stats["q_client"] += 1

            op_date = parse_date(r[C_DATE_OP])
            if op_date is None:
                if r[C_DATE_OP] is not None:
                    stats["bad_date"] += 1
                op_date = parse_date(r[C_DATE_PAY])
            if op_date is None:
                stats["skipped"] += 1
                continue
            if r[C_DATE_OP] is not None and not isinstance(r[C_DATE_OP], (datetime, date)):
                stats["bad_date"] += 1
            pay_date = parse_date(r[C_DATE_PAY], fallback=op_date)
            # Известная ошибка ввода: часть июньских операций записана февралём.
            # Журнал ведётся за июнь 2026 — возвращаем такие даты в июнь.
            if op_date and op_date.year == 2026 and op_date.month == 2:
                op_date = op_date.replace(month=6)
            if pay_date and pay_date.year == 2026 and pay_date.month == 2:
                pay_date = pay_date.replace(month=6)

            acc = method_account(r[C_METHOD], accounts)
            note = " · сумма уточняется" if uncertain else ""

            if op_type in INCOME_TYPES:
                paid = Decimal("0") if op_type == "Не заплатил" else amount
                if op_type == "Не заплатил":
                    stats["unpaid"] += 1
                sales.append(Sale(
                    client_code=str(client or "—")[:120],
                    amount_mode=Sale.AmountMode.DIRECT, weight_kg=None, places=1, account=acc,
                    price_som=amount, paid_som=paid, cost_som=Decimal("0"), margin_som=amount,
                    date=op_date, payment_date=pay_date, **snap,
                ))
                stats["income"] += 1
            else:
                # «Расход» ИЛИ строка без явного типа дохода, но с видом операции
                # (командировочные, зарплата и т.п.) — это расход, не продажа.
                kind = str(r[C_KIND] or "")
                is_cogs = any(h in kind.lower() for h in COGS_HINTS)
                expenses.append(Expense(
                    account=acc,
                    category=ExpenseCategory.COGS if is_cogs else ExpenseCategory.OPEX,
                    opex_article=None if is_cogs else OpexArticle.OTHER,
                    amount=amount, paid_amount=amount, description=((kind or "Расход") + note)[:500],
                    date=op_date, payment_date=pay_date,
                ))
                stats["expense"] += 1

        Sale.objects.bulk_create(sales, batch_size=500)
        Expense.objects.bulk_create(expenses, batch_size=500)

        self.stdout.write(self.style.SUCCESS(
            f"✔ Продажи: {stats['income']} (из них не оплачено: {stats['unpaid']}), расходы: {stats['expense']}"
        ))
        self.stdout.write(self.style.WARNING(
            f"  Очищено «?»: сумм {stats['q_amount']}, клиентов {stats['q_client']}; "
            f"битых дат исправлено: {stats['bad_date']}; пропущено строк: {stats['skipped']}"
        ))
        self.stdout.write(self.style.SUCCESS("Готово. Loko Express загружен из журнала «Локо1»."))
