"""Импорт раздела «Наличка» (Loko Express) из Excel-журнала.

Источник: «Финансовый учет карго компании Локо наличка.xlsx», лист
«4. Журнал операций» (заголовки в строке 5). Журнал содержит ВСЕ операции
(МБанк, Оптима, наличка) — берём ТОЛЬКО строки с наличными метками в колонке
«Комментарий» (банки импортируются отдельно из PDF, иначе двойной счёт).

Правило: метка «Комментарий» ∈ набор наличных + тип операции = поступление →
Sale (выручка) на счёт «Наличные». Контроль: выручка = 231 781.

Колонки: 2 «Дата операции», 3 «Дата оплаты», 6 «Тип операции»,
14 «Контрагент», 36 «Сумма по тетради», 37 «Комментарий».
"""

import re
import warnings
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from finance.models import Account, AppSettings, Currency, Expense, Module
from express.models import Sale

DEFAULT_PATH = str(Path.home() / "Downloads" / "Финансовый учет карго компании Локо наличка.xlsx")
SHEET = "4. Журнал операций"
HEADER_ROW = 5
# 1-based номера колонок (как в Excel).
C_DATE_OP, C_DATE_PAY, C_TYPE, C_CLIENT, C_SUM, C_COMMENT = 2, 3, 6, 14, 36, 37
ACCOUNT_NAME = "Наличные"
INCOME_TYPES = {"Поступление", "Приход", "Не заплатил"}
# Наличные метки (выбор пользователя в фильтре «Комментарий»). Опт/Оптима-за-кг
# и «операция дублируется» — НЕ наличка.
CASH_COMMENTS = {
    "Наличка", "Наличные", "Наличка 250 за кг", "Наличка, 220 за кг",
    "Наличка, 240 за кг", "Опт Нал", "Оптима, Наличка",
}


def clean_amount(value):
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        s = value.split("/")[0].replace("?", "").replace("\xa0", " ")
        s = re.sub(r"(?<=\d)[ ](?=\d)", "", s)
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
            if y > 2100:
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


def june_fix(d):
    """Известная ошибка ввода: часть июньских операций записана февралём 2026."""
    if d and d.year == 2026 and d.month == 2:
        return d.replace(month=6)
    return d


class Command(BaseCommand):
    help = "Импорт раздела «Наличка» из Excel-журнала на счёт «Наличные» (выручка 231 781)."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=DEFAULT_PATH)

    @transaction.atomic
    def handle(self, *args, **opts):
        try:
            import openpyxl
        except ImportError:
            raise CommandError("Нужен openpyxl")

        path = opts["path"]
        if not Path(path).exists():
            raise CommandError(f"Файл не найден:\n{path}\nУкажите --path")

        cfg = AppSettings.load()
        acc, _ = Account.objects.get_or_create(
            name=ACCOUNT_NAME,
            defaults=dict(kind=Account.Kind.CASH, currency=Currency.KGS, module=Module.EXPRESS),
        )
        Sale.objects.filter(account=acc, created_by__isnull=True).delete()
        Expense.objects.filter(account=acc, created_by__isnull=True).delete()

        snap = dict(price_per_kg_usd=cfg.price_per_kg_usd, usd_rate_som=cfg.usd_rate_som,
                    cost_per_kg_som=cfg.base_cost_per_kg_som)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb[SHEET]

        sales = []
        revenue = Decimal("0")
        unpaid = 0
        skip_amt, skip_n = Decimal("0"), 0

        for r in ws.iter_rows(min_row=HEADER_ROW + 1, values_only=True):
            comment = r[C_COMMENT - 1]
            if comment is None or str(comment).strip() not in CASH_COMMENTS:
                continue
            amount = clean_amount(r[C_SUM - 1])
            op_type = str(r[C_TYPE - 1] or "").strip()
            op_date = june_fix(parse_date(r[C_DATE_OP - 1]))
            # Наличный раздел = только поступления; прочее (строки без типа и т.п.) пропускаем.
            if op_type not in INCOME_TYPES or op_date is None:
                skip_amt += amount
                skip_n += 1
                continue
            pay_date = june_fix(parse_date(r[C_DATE_PAY - 1], fallback=op_date))
            paid = Decimal("0") if op_type == "Не заплатил" else amount
            if op_type == "Не заплатил":
                unpaid += 1
            client = r[C_CLIENT - 1]
            sales.append(Sale(
                client_code=str(client if client is not None else "—")[:120],
                amount_mode=Sale.AmountMode.DIRECT, weight_kg=None, places=1, account=acc,
                price_som=amount, paid_som=paid, cost_som=Decimal("0"), margin_som=amount,
                date=op_date, payment_date=pay_date, **snap,
            ))
            revenue += amount

        Sale.objects.bulk_create(sales, batch_size=500)

        self.stdout.write(self.style.SUCCESS(
            f"✔ Счёт «{ACCOUNT_NAME}»: продаж {len(sales)} на {revenue:,.2f}"
            + (f" (из них не оплачено: {unpaid})" if unpaid else "")
        ))
        if skip_n:
            self.stdout.write(self.style.WARNING(
                f"  Пропущено наличных строк без типа поступления: {skip_n} на {skip_amt:,.2f}"
            ))
        self.stdout.write(
            f"  Контроль выручки: {revenue:,.2f}  (эталон 231 781.00)"
        )
        if abs(revenue - Decimal("231781")) < Decimal("0.5"):
            self.stdout.write(self.style.SUCCESS("  ✓ Сходится с эталоном."))
        else:
            self.stdout.write(self.style.ERROR(f"  ✗ РАСХОЖДЕНИЕ {revenue - Decimal('231781'):,.2f}"))
