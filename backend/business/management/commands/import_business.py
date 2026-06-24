"""Импорт реальных данных Loko Business за период 01–23.06.2026.

Источник: «Локо Бизнес 2.0.xlsx» → лист «Журнал операций» (двусторонние проводки),
который, как проверено, корректно собран из исходника «Баяман.xlsx».

Курс юаня (отображение/ОПиУ) = 13.1. Доллар (для долгов) = 87.5.

Маппинг типов операций на модели системы:
  Приход клиента      → Deposit (RECOGNIZED) на Мбанк            → выручка ОПиУ
  Аванс клиента       → Deposit (HELD)                          → не выручка
  Закуп товара        → Expense (COGS)                          → себестоимость ОПиУ
  Изъятие собственника→ Expense (OWNER)
  Аванс поставщику    → Expense (SUPPLIER)
  Прочий расход       → Expense (OPEX, статья «Прочие»)
  Внутренний перевод  → Transfer (одна валюта)
  Конвертация валюты  → Transfer (Мбанк сом → китайский счёт юань, по курсу)
  Погашение ДЗ        → Deposit (HELD, приток на Мбанк, помечен «Погашение ДЗ»)
  Погашение КЗ        → Expense (SUPPLIER, отток с Мбанк)
"""

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from finance.models import Account, AppSettings, Currency, Expense, ExpenseCategory, Module, OpexArticle, Transfer
from business.models import Debt, Deposit

D = lambda x: Decimal(str(x))
Y = 2026

# Счета Business: (name, currency, initial_balance)
ACCOUNTS = [
    ("Вичат", Currency.CNY, 20187),
    ("Алипей", Currency.CNY, 19192),
    ("Мбанк (Business)", Currency.KGS, 0),  # по исходнику «Баяман» (в 2.0 стоял 33 из банк-выписки)
    ("ICBC", Currency.CNY, 8397),
    ("ICBC 0687", Currency.CNY, 4622),
    ("9148 карта", Currency.CNY, 0),
    ("Наличные юань", Currency.CNY, 0),
]
MBANK = "Мбанк (Business)"

# Долги — остаток на конец периода (лист «Задолженность»). $ → сом по 87.5.
DEBTS = [
    ("RECEIVABLE", "Мира эже", 258445, Currency.KGS),       # 346000 − 87555
    ("RECEIVABLE", "Абдулла аке", 50494, Currency.KGS),
    ("RECEIVABLE", "Бекжан", 21000, Currency.KGS),
    ("RECEIVABLE", "Рустам", 20000, Currency.KGS),
    ("RECEIVABLE", "Гулгаакы эже", 49800, Currency.KGS),
    ("RECEIVABLE", "Назира эже", 18400, Currency.KGS),
    ("RECEIVABLE", "Кулмамат ака", 14600, Currency.CNY),
    ("PAYABLE", "Караванчи", round(1138 * 87.5), Currency.KGS),
    ("PAYABLE", "Селли бухгалтер", 3700, Currency.CNY),
    ("PAYABLE", "Карго", round(3 * 87.5), Currency.KGS),     # остаток 3$
]

# (контрагент, счёт Мбанк, сумма сом, день)
CLIENT_INCOME = [
    ("Нурсултан ака", 13100, 16), ("Суита эже", 256400, 17), ("Ислам ака", 69875, 17),
    ("Анар Токтосунова", 43230, 18), ("Буниса эже", 92000, 20), ("Мухамадали", 46000, 23),
]
CLIENT_ADVANCE = [("Авенир", 300000, 16), ("Азамжон ака", 100000, 17)]

# (контрагент, счёт, сумма в валюте счёта, день)
COGS = [
    ("Раян отель", "Вичат", 448, 16), ("Гулгаакы эже", "Вичат", 1960, 16),
    ("Нурсултан ака", "Вичат", 680, 16), ("Ислам ака", "Вичат", 700, 17),
    ("Суита эже", "ICBC", 5075, 17), ("Суита эже (мбанк)", MBANK, 172524, 18),
    ("Буниса эже", "ICBC", 6150, 23), ("Частная школа", "9148 карта", 6000, 23),
    ("Мухамадали", "9148 карта", 2100, 23),
]
OWNER = [("ICBC", 100, 16), ("ICBC", 75.5, 17), ("9148 карта", 500, 17)]
SUPPLIER_ADVANCE = [("Авенир", "ICBC", 15438, 17), ("Азамжон ака", "9148 карта", 2500, 18)]
OTHER_EXP = [("Прочее", "9148 карта", 800, 23)]

# Внутренний перевод (одна валюта): (счёт-источник, счёт-получатель, сумма, день)
INTERNAL = [
    ("Алипей", "ICBC", 19192, 17), ("Вичат", "9148 карта", 10000, 17),
    ("Вичат", "9148 карта", 12738, 17), ("Алипей", "ICBC", 10000, 19),
    ("Алипей", "Наличные юань", 20000, 19), ("ICBC 0687", "Наличные юань", 4600, 19),
    ("Алипей", "9148 карта", 10000, 23),
]
# Конвертация: (счёт-источник сом, сумма сом, счёт-получатель юань, сумма юань, курс, день)
CONVERT = [
    (MBANK, 6450, "Вичат", 500, 12.9, 17), (MBANK, 6192, "Вичат", 480, 12.9, 18),
    (MBANK, 500000, "Алипей", 38168, 13.1, 18), (MBANK, 2580, "Вичат", 200, 12.9, 19),
    (MBANK, 180000, "Алипей", 13740, 13.1, 19), (MBANK, 90000, "Вичат", 6949.8, 12.95, 20),
    (MBANK, 2580, "Вичат", 200, 12.9, 21),
]
PAY_DZ = [("Мира эже", 87555, 18)]   # приток на Мбанк (погашение ДЗ)
PAY_KZ = [("Карго", 40000, 23)]      # отток с Мбанк (погашение КЗ)


class Command(BaseCommand):
    help = "Импорт реальных операций Loko Business (01–23.06.2026) из «Локо Бизнес 2.0»."

    @transaction.atomic
    def handle(self, *args, **options):
        AppSettings.load()
        # Курс юаня 13.1; налог на прибыль 0 (в реальной модели Локо его нет — задаётся при необходимости).
        AppSettings.objects.filter(pk=1).update(cny_to_kgs_rate=D("13.1"), profit_tax_rate=D("0"))
        self.stdout.write(self.style.SUCCESS("✔ Курс юаня = 13.1, налог = 0%"))

        acc = {}
        for name, ccy, init in ACCOUNTS:
            obj, _ = Account.objects.update_or_create(
                name=name,
                defaults={
                    "kind": Account.Kind.BANK if name != "Наличные юань" else Account.Kind.CASH,
                    "currency": ccy,
                    "module": Module.BUSINESS,
                    "initial_balance": D(init),
                },
            )
            acc[name] = obj

        # Чистим прошлые бизнес-операции (идемпотентность).
        biz_ids = [a.id for a in acc.values()]
        Deposit.objects.filter(account_id__in=biz_ids).delete()
        Expense.objects.filter(account_id__in=biz_ids).delete()
        Transfer.objects.filter(from_account_id__in=biz_ids).delete()
        Transfer.objects.filter(to_account_id__in=biz_ids).delete()
        Debt.objects.all().delete()

        def dt(day):
            return date(Y, 6, day)

        # Долги
        for kind, who, amount, ccy in DEBTS:
            Debt.objects.create(
                kind=kind, counterparty=who, amount=D(amount), currency=ccy,
                status=Debt.Status.OPEN, date=dt(1), note="Импорт из Локо Бизнес 2.0",
            )

        # Приход клиента → выручка (Deposit RECOGNIZED)
        for who, amount, day in CLIENT_INCOME:
            dep = Deposit.objects.create(
                source=who, account=acc[MBANK], amount=D(amount),
                status=Deposit.Status.HELD, date=dt(day), note="Приход клиента",
            )
            dep.recognize_as_revenue(when=dt(day))

        # Аванс клиента → Deposit HELD (не выручка)
        for who, amount, day in CLIENT_ADVANCE:
            Deposit.objects.create(
                source=who, account=acc[MBANK], amount=D(amount),
                status=Deposit.Status.HELD, date=dt(day), note="Аванс клиента (не выручка)",
            )

        # Погашение ДЗ → приток на Мбанк
        for who, amount, day in PAY_DZ:
            Deposit.objects.create(
                source=f"Погашение ДЗ — {who}", account=acc[MBANK], amount=D(amount),
                status=Deposit.Status.HELD, date=dt(day), note="Погашение дебиторской задолженности",
            )

        def expense(account, category, amount, day, desc, article=None):
            Expense.objects.create(
                account=account, category=category, opex_article=article,
                amount=D(amount), paid_amount=D(amount), description=desc,
                date=dt(day), payment_date=dt(day),
            )

        for who, account, amount, day in COGS:
            expense(acc[account], ExpenseCategory.COGS, amount, day, f"Закуп товара — {who}")
        for account, amount, day in OWNER:
            expense(acc[account], ExpenseCategory.OWNER, amount, day, "Изъятие собственника")
        for who, account, amount, day in SUPPLIER_ADVANCE:
            expense(acc[account], ExpenseCategory.SUPPLIER, amount, day, f"Аванс поставщику — {who}")
        for who, account, amount, day in OTHER_EXP:
            expense(acc[account], ExpenseCategory.OPEX, amount, day, f"Прочий расход — {who}", OpexArticle.OTHER)
        for who, amount, day in PAY_KZ:
            expense(acc[MBANK], ExpenseCategory.SUPPLIER, amount, day, f"Погашение КЗ — {who}")

        # Внутренние переводы (одна валюта)
        for src, dst, amount, day in INTERNAL:
            Transfer.objects.create(
                from_account=acc[src], to_account=acc[dst], amount=D(amount),
                to_amount=D(amount), rate=D(1), date=dt(day), description="Внутренний перевод",
            )
        # Конвертации
        for src, som, dst, yuan, rate, day in CONVERT:
            Transfer.objects.create(
                from_account=acc[src], to_account=acc[dst], amount=D(som),
                to_amount=D(yuan), rate=D(rate), date=dt(day), description="Покупка юаня",
            )

        self.stdout.write(self.style.SUCCESS(
            f"✔ Импортировано: {len(CLIENT_INCOME)} приходов, {len(CLIENT_ADVANCE)} авансов, "
            f"{len(COGS)} закупов, {len(INTERNAL)} переводов, {len(CONVERT)} конвертаций, "
            f"{len(DEBTS)} долгов."
        ))
        self.stdout.write(self.style.SUCCESS("Готово. Данные Loko Business загружены."))
