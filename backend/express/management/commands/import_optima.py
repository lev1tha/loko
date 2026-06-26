"""Импорт выписок Оптима Банк (Loko Express): все счета сводятся в счёт «Оптима Банк».

Простое правило — по знаку/колонке:
    приход → Sale (выручка)
    расход → Expense

Два формата выписок (определяются автоматически):
  * Личная карта: «Дата | Детали операции | Сумма операции | Комиссия».
        «Сумма операции» со знаком: −X = расход, X = приход (пополнение).
  * Счёт ИП (Справка-выписка): колонки «Дебет (списание) | Кредит (поступление)».
        Кредит → приход, Дебет → расход.

Баланс счёта «Оптима Банк» = Σ входящих остатков выписок + Σприход − Σрасход;
сходится с суммой исходящих остатков (для ИП-выписки исходящий = вход + Кредит − Дебет).

Идемпотентно: импортные строки (created_by пуст) на счёте «Оптима Банк»
удаляются и создаются заново; ручной ввод с сайта сохраняется.
"""

import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from finance.models import (
    Account, AppSettings, Currency, Expense, ExpenseCategory, Module, OpexArticle,
)
from express.models import Sale

DEFAULT_DIR = str(Path.home() / "Documents" / "loko-express" / "optima")
ACCOUNT_NAME = "Оптима Банк"
TWO = Decimal("0.01")

# Личная карта: «дата ДЕТАЛИ ±сумма KGS комиссия KGS» (детали — в одну строку).
CARD_RE = re.compile(
    r"(\d{2}\.\d{2}\.\d{4})\s+([^\n]+?)\s+(-?\d[\d  .,]*?)\s*KGS\s+([\d  .,]+?)\s*KGS"
)


def parse_num(s):
    """Два формата: '36 303,88' (запятая=копейки) и '1,234.56' (запятая=тысячи)."""
    s = str(s).replace("\xa0", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return None


def parse_date(s):
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", str(s).strip())
    if not m:
        return None
    d, mo, y = map(int, m.groups())
    try:
        return datetime(y, mo, d).date()
    except ValueError:
        return None


class Command(BaseCommand):
    help = "Импорт выписок Оптима Банк (все счета → один счёт «Оптима Банк»)."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=DEFAULT_DIR, help="Папка (или файл) с PDF-выписками Оптимы")

    @transaction.atomic
    def handle(self, *args, **opts):
        try:
            import pdfplumber
        except ImportError:
            raise CommandError("Нужен pdfplumber: pip install pdfplumber")

        p = Path(opts["path"])
        files = sorted(p.glob("*.pdf")) if p.is_dir() else [p]
        if not files:
            raise CommandError(f"PDF-выписки не найдены: {p}")

        cfg = AppSettings.load()
        acc, _ = Account.objects.get_or_create(
            name=ACCOUNT_NAME,
            defaults=dict(kind=Account.Kind.BANK, currency=Currency.KGS, module=Module.EXPRESS),
        )
        Sale.objects.filter(account=acc, created_by__isnull=True).delete()
        Expense.objects.filter(account=acc, created_by__isnull=True).delete()

        snap = dict(price_per_kg_usd=cfg.price_per_kg_usd, usd_rate_som=cfg.usd_rate_som,
                    cost_per_kg_som=cfg.base_cost_per_kg_som)

        sales, expenses = [], []
        opening_total = Decimal("0")
        closing_total = Decimal("0")
        per_file = []

        for f in files:
            with pdfplumber.open(str(f)) as pdf:
                full = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
                is_debcred = "Дебет" in full and "Кредит" in full
                fin = fout = Decimal("0")

                if is_debcred:
                    for pg in pdf.pages:
                        for tbl in (pg.extract_tables() or []):
                            for row in tbl:
                                c = [(x or "").replace("\n", " ").strip() for x in row]
                                if len(c) < 6:
                                    continue
                                d = parse_date(c[0])
                                if not d:
                                    continue
                                deb = parse_num(c[4]) if c[4] else None
                                cred = parse_num(c[5]) if c[5] else None
                                label = (c[7] if len(c) > 7 and c[7] else "Оптима").strip()
                                if cred and cred > 0:
                                    sales.append(self._sale(acc, cred, d, label, snap)); fin += cred
                                if deb and deb > 0:
                                    expenses.append(self._exp(acc, deb, d, label)); fout += deb
                    op = self._find(full, r"Входящий остаток:\s*([\d  .,]+)")
                else:
                    for m in CARD_RE.finditer(full):
                        ds, det, amt, _comm = m.groups()
                        v, d = parse_num(amt), parse_date(ds)
                        if v is None or d is None or v == 0:
                            continue
                        label = re.sub(r"\s+", " ", det).strip()
                        if v < 0:
                            expenses.append(self._exp(acc, -v, d, label)); fout += -v
                        else:
                            sales.append(self._sale(acc, v, d, label, snap)); fin += v
                    op = self._find(full, r"[Оо]статок на начало периода:\s*([\d  .,]+)")

                cl = self._find(full, r"[Оо]статок на конец периода:\s*([\d  .,]+)")
                if cl is None:
                    cl = op + fin - fout          # ИП-выписка: исходящий не указан — вычисляем
                opening_total += op
                closing_total += cl
                per_file.append((f.name, "ИП Дт/Кт" if is_debcred else "карта", op, cl, fin, fout))

        acc.initial_balance = opening_total
        acc.save()

        Sale.objects.bulk_create(sales, batch_size=500)
        Expense.objects.bulk_create(expenses, batch_size=500)

        rev = sum((s.price_som for s in sales), Decimal("0"))
        exp = sum((e.amount for e in expenses), Decimal("0"))
        balance = opening_total + rev - exp

        self.stdout.write("Файлы:")
        for name, kind, op, cl, fi, fo in per_file:
            self.stdout.write(f"  [{kind}] {name}: вход {op:,.2f} → выход {cl:,.2f} | приход {fi:,.2f} / расход {fo:,.2f}")
        self.stdout.write(self.style.SUCCESS(
            f"\n✔ Счёт «{ACCOUNT_NAME}»: продаж {len(sales)} на {rev:,.2f}; расходов {len(expenses)} на {exp:,.2f}"
        ))
        self.stdout.write(
            f"  Входящий остаток (сумма): {opening_total:,.2f}\n"
            f"  Расчётный баланс: {opening_total:,.2f} + {rev:,.2f} − {exp:,.2f} = {balance:,.2f}\n"
            f"  Сумма исходящих по выпискам: {closing_total:,.2f}"
        )
        if abs(balance - closing_total) < TWO:
            self.stdout.write(self.style.SUCCESS("  ✓ Баланс сходится с выписками."))
        else:
            self.stdout.write(self.style.ERROR(f"  ✗ РАСХОЖДЕНИЕ {balance - closing_total:,.2f}"))

    @staticmethod
    def _find(text, pattern):
        m = re.search(pattern, text)
        return parse_num(m.group(1)) if m else None

    def _sale(self, acc, amount, d, label, snap):
        amount = amount.quantize(TWO, rounding=ROUND_HALF_UP)
        return Sale(
            client_code=(label or "Приход")[:120], amount_mode=Sale.AmountMode.DIRECT,
            weight_kg=None, places=1, account=acc,
            price_som=amount, paid_som=amount, cost_som=Decimal("0"), margin_som=amount,
            date=d, payment_date=d, **snap,
        )

    def _exp(self, acc, amount, d, label):
        amount = amount.quantize(TWO, rounding=ROUND_HALF_UP)
        return Expense(
            account=acc, category=ExpenseCategory.OPEX, opex_article=OpexArticle.OTHER,
            amount=amount, paid_amount=amount, description=(label or "Расход")[:500],
            date=d, payment_date=d,
        )
