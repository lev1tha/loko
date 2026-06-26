"""Бэкфилл снапшот-курса юаня на существующие CNY-операции.

Все текущие данные введены при курсе 13.1 и сверены с Excel до копейки.
Фиксируем этот курс на каждой CNY-операции, чтобы история больше не «плыла»
при смене текущего курса в Настройках. KGS-операции остаются с rate=NULL.
"""

from decimal import Decimal

from django.db import migrations


def backfill(apps, schema_editor):
    AppSettings = apps.get_model("finance", "AppSettings")
    Account = apps.get_model("finance", "Account")
    Expense = apps.get_model("finance", "Expense")
    Transfer = apps.get_model("finance", "Transfer")
    Deposit = apps.get_model("business", "Deposit")
    Debt = apps.get_model("business", "Debt")

    cfg = AppSettings.objects.filter(pk=1).first()
    rate = cfg.cny_to_kgs_rate if cfg else Decimal("13.1")

    Account.objects.filter(currency="CNY").update(initial_kgs_rate=rate)
    Expense.objects.filter(account__currency="CNY").update(kgs_rate=rate)
    Transfer.objects.filter(
        from_account__currency="CNY"
    ).update(kgs_rate=rate)
    Transfer.objects.filter(
        to_account__currency="CNY"
    ).update(kgs_rate=rate)
    Deposit.objects.filter(currency="CNY").update(kgs_rate=rate)
    Debt.objects.filter(currency="CNY").update(kgs_rate=rate)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0006_account_initial_kgs_rate_expense_kgs_rate_and_more"),
        ("business", "0002_debt_kgs_rate_deposit_kgs_rate"),
    ]

    operations = [migrations.RunPython(backfill, noop)]
