"""Импорт выписок МБанк (Loko Express): все счета сводятся в один счёт «МБанк».

Простое правило — по знаку суммы:
    +  → приход → Sale (выручка)
    −  → расход → Expense

Два формата выписок (определяются автоматически):
  * Корпоративный (юрлицо): таблица с колонками «Оборот Дт / Оборот Кт».
        Оборот Кт → приход (+), Оборот Дт → расход (−).
  * Личный (физлицо): строки «дата время Описание: ±сумма …».

Баланс счёта «МБанк» = Σ входящих остатков всех выписок + Σ(+) − Σ(−);
сходится с суммой исходящих остатков по выпискам.

Идемпотентно: импортные строки (created_by пуст) на счёте «МБанк» удаляются
и создаются заново; ручной ввод с сайта (created_by задан) сохраняется.
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

DEFAULT_DIR = str(Path.home() / "Documents" / "loko-express" / "mbank")
ACCOUNT_NAME = "МБанк"
TWO = Decimal("0.01")
# Наши держатели счетов — для отсева внутренних переводов между своими счетами.
OUR_PHONES = {"996220105653", "996776904207"}  # Бектур, Каныкей

# Строка операции в личной выписке: дата время Описание: ±сумма [детали…]
PERSONAL_RE = re.compile(
    r"(\d{2}\.\d{2}\.\d{4})\s+\d{2}:\d{2}\s+(.+?):\s*([+\-])\s*([\d  .,]+)\s*(.*?)"
    r"(?=\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}|\Z)",
    re.S,
)


def parse_num(s):
    """Два формата чисел: '300,000.00' (запятая=тысячи) и '25 940,00' (запятая=копейки)."""
    s = str(s).replace("\xa0", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(",", "")          # корп.: запятая — разделитель тысяч
    elif "," in s:
        s = s.replace(",", ".")         # личный: запятая — десятичная
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


def counterparty(text):
    """Имя контрагента после «996XXXXXXXXX/ Имя /», иначе пусто."""
    m = re.search(r"996\d{9}/\s*([^/]+?)\s*/", text)
    return m.group(1).strip() if m else ""


class Command(BaseCommand):
    help = "Импорт выписок МБанк (все счета → один счёт «МБанк»). + = приход, − = расход."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=DEFAULT_DIR, help="Папка (или файл) с PDF-выписками МБанк")

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
        # Чистим прошлый импорт (ручной ввод с сайта сохраняем).
        Sale.objects.filter(account=acc, created_by__isnull=True).delete()
        Expense.objects.filter(account=acc, created_by__isnull=True).delete()

        snap = dict(price_per_kg_usd=cfg.price_per_kg_usd, usd_rate_som=cfg.usd_rate_som,
                    cost_per_kg_som=cfg.base_cost_per_kg_som)

        txns = []                      # все операции: dict(date, sign, amt, text, label)
        opening_total = Decimal("0")
        closing_total = Decimal("0")
        per_file = []

        for f in files:
            with pdfplumber.open(str(f)) as pdf:
                page1 = pdf.pages[0].extract_text() or ""
                full = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
                is_corp = "Оборот" in full and "Назначение платеж" in full

                op, cl = self._balances(page1, full, is_corp)
                opening_total += op
                closing_total += cl

                n = 0
                if is_corp:
                    for pg in pdf.pages:
                        for tbl in (pg.extract_tables() or []):
                            for row in tbl:
                                c = [(x or "").replace("\n", " ").strip() for x in row]
                                if len(c) < 6:
                                    continue
                                d = parse_date(c[1])
                                if not d:
                                    continue
                                dt, kt = parse_num(c[3]), parse_num(c[4])
                                text = (c[5] + " " + c[2]).strip()
                                name = c[2].split(", ИНН")[0].strip()
                                label = (c[5].strip() + (" — " + name if name else "")).strip(" —")
                                if kt and kt > 0:
                                    txns.append(dict(date=d, sign="+", amt=kt, text=text, label=label)); n += 1
                                if dt and dt > 0:
                                    txns.append(dict(date=d, sign="-", amt=dt, text=text, label=label)); n += 1
                else:
                    for m in PERSONAL_RE.finditer(full):
                        ds, desc, sign, amt, detail = m.groups()
                        v, d = parse_num(amt), parse_date(ds)
                        if v is None or d is None or v == 0:
                            continue
                        text = re.sub(r"\s+", " ", desc + " " + detail).strip()
                        cp = counterparty(text)
                        label = (desc.strip() + (" — " + cp if cp else "")).strip()
                        txns.append(dict(date=d, sign=sign, amt=v, text=text, label=label)); n += 1

                per_file.append((f.name, "корп" if is_corp else "личн", op, cl, n))

        # --- Отсев внутренних переводов между своими счетами (убираем задвоение выручки) ---
        # 1) Обнал (Тез→Бектур): строки с меткой «обналичование» — обе ноги равны (нетто 0).
        # 2) Сметания Бектур↔Каныкей: пара расход↔приход с НАШИМИ телефонами, равная сумма, ≤3 дней.
        # Только спаренные/сбалансированные строки — баланс счёта не меняется.
        internal = set()
        for t in txns:
            if "обналич" in t["text"].lower():
                internal.add(id(t))

        def our_phone(text):
            m = re.search(r"(996\d{9})", text)
            return bool(m and m.group(1) in OUR_PHONES)

        used = set()
        deb = sorted([t for t in txns if t["sign"] == "-" and id(t) not in internal and our_phone(t["text"])],
                     key=lambda r: -r["amt"])
        cred = [t for t in txns if t["sign"] == "+" and id(t) not in internal and our_phone(t["text"])]
        for d in deb:
            for c in cred:
                if id(c) in used:
                    continue
                if c["amt"] == d["amt"] and abs((c["date"] - d["date"]).days) <= 3:
                    internal.add(id(d)); internal.add(id(c)); used.add(id(c)); break

        n_internal = len(internal)
        internal_sum = sum((t["amt"] for t in txns if t["sign"] == "+" and id(t) in internal), Decimal("0"))

        sales, expenses = [], []
        for t in txns:
            if id(t) in internal:
                continue
            if t["sign"] == "+":
                sales.append(self._sale(acc, t["amt"], t["date"], t["label"], snap))
            else:
                expenses.append(self._exp(acc, t["amt"], t["date"], t["label"]))

        # Входящий остаток счёта = сумма входящих по выпискам → консолидир. баланс сойдётся.
        acc.initial_balance = opening_total
        acc.save()

        Sale.objects.bulk_create(sales, batch_size=500)
        Expense.objects.bulk_create(expenses, batch_size=500)

        rev = sum((s.price_som for s in sales), Decimal("0"))
        exp = sum((e.amount for e in expenses), Decimal("0"))
        balance = opening_total + rev - exp

        self.stdout.write("Файлы:")
        for name, kind, op, cl, n in per_file:
            self.stdout.write(f"  [{kind}] {name}: вход {op:,.2f} → выход {cl:,.2f} | строк {n}")
        self.stdout.write(self.style.SUCCESS(
            f"\n✔ Счёт «{ACCOUNT_NAME}»: продаж {len(sales)} на {rev:,.2f}; расходов {len(expenses)} на {exp:,.2f}"
        ))
        self.stdout.write(
            f"  Внутренних отсеяно: {n_internal} строк (обнал+сметания) на {internal_sum:,.2f} с каждой стороны\n"
            f"  Входящий остаток (сумма): {opening_total:,.2f}\n"
            f"  Расчётный баланс: {opening_total:,.2f} + {rev:,.2f} − {exp:,.2f} = {balance:,.2f}\n"
            f"  Сумма исходящих по выпискам: {closing_total:,.2f}"
        )
        if abs(balance - closing_total) < TWO:
            self.stdout.write(self.style.SUCCESS("  ✓ Баланс сходится с выписками."))
        else:
            self.stdout.write(self.style.ERROR(
                f"  ✗ РАСХОЖДЕНИЕ {balance - closing_total:,.2f} — проверь парсинг."
            ))

    def _balances(self, page1, full, is_corp):
        if is_corp:
            # «Исходящий остаток» — на последней странице, ищем по всему тексту.
            mo = re.search(r"[Вв]ходящий остаток:\s*([\d  .,]+)", full)
            mc = re.search(r"[Ии]сходящий остаток:\s*([\d  .,]+)", full)
        else:
            # «… 2,89 KGS 110,77 KGS» — два остатка подряд (вход / выход).
            m = re.search(r"([\d  .,]+)\s*KGS\s+([\d  .,]+)\s*KGS", page1)
            mo = mc = None
            if m:
                return (parse_num(m.group(1)) or Decimal("0"), parse_num(m.group(2)) or Decimal("0"))
        op = parse_num(mo.group(1)) if mo else Decimal("0")
        cl = parse_num(mc.group(1)) if mc else Decimal("0")
        return (op or Decimal("0"), cl or Decimal("0"))

    def _sale(self, acc, amount, d, label, snap):
        amount = amount.quantize(TWO, rounding=ROUND_HALF_UP)
        return Sale(
            client_code=(label or "Приход")[:120], amount_mode=Sale.AmountMode.DIRECT,
            weight_kg=None, places=1, account=acc,
            price_som=amount, paid_som=amount, cost_som=Decimal("0"), margin_som=amount,
            date=d, payment_date=d, **snap,
        )

    def _exp(self, acc, amount, d, label):
        # Банковские оттоки = карго-себестоимость (касса/ОДДС). В ОПиУ себестоимость
        # считается как % от выручки (документ-спецификация), а не из этих строк.
        amount = amount.quantize(TWO, rounding=ROUND_HALF_UP)
        return Expense(
            account=acc, category=ExpenseCategory.COGS, opex_article=None,
            amount=amount, paid_amount=amount, description=(label or "Расход")[:500],
            date=d, payment_date=d,
        )
