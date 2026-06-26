"""Полная очистка данных Loko Express.

Удаляет (в правильном порядке из-за PROTECT на FK счёта):
  1. Продажи (`express.Sale`) на счетах модуля EXPRESS;
  2. Расходы (`finance.Expense`) на счетах модуля EXPRESS;
  3. Переводы (`finance.Transfer`) с/на любой Express-счёт;
  4. Сами счета (`finance.Account`) модуля EXPRESS (если не указан --keep-accounts).

НЕ трогает Loko Business (депозиты, долги, юаневые счета) и AppSettings
(курсы/цены/налоги). Балансы счетов вычисляются из операций, отдельного
сброса не требуют.

Безопасность: по умолчанию это DRY-RUN — только печатает, что будет удалено.
Реальное удаление выполняется ТОЛЬКО с флагом --confirm.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from finance.models import Account, Expense, Module, Transfer
from express.models import Sale


class Command(BaseCommand):
    help = "Очистить данные Loko Express (продажи, расходы, переводы и счета). По умолчанию dry-run; удаление — с --confirm."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Выполнить удаление. Без этого флага команда только показывает, что будет удалено.",
        )
        parser.add_argument(
            "--keep-accounts",
            action="store_true",
            help="Удалить только операции, сами Express-счета оставить.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        confirm = options["confirm"]
        keep_accounts = options["keep_accounts"]

        express_accounts = Account.objects.filter(module=Module.EXPRESS)
        sales = Sale.objects.filter(account__module=Module.EXPRESS)
        expenses = Expense.objects.filter(account__module=Module.EXPRESS)
        transfers = Transfer.objects.filter(
            Q(from_account__module=Module.EXPRESS) | Q(to_account__module=Module.EXPRESS)
        )

        n_sales = sales.count()
        n_exp = expenses.count()
        n_tr = transfers.count()
        acc_names = list(express_accounts.values_list("name", flat=True))

        self.stdout.write("Будет удалено из Loko Express:")
        self.stdout.write(f"  • Продажи (Sale):            {n_sales}")
        self.stdout.write(f"  • Расходы (Expense):         {n_exp}")
        self.stdout.write(f"  • Переводы с/на Express:     {n_tr}")
        if keep_accounts:
            self.stdout.write(f"  • Счета Express:             ОСТАВЛЯЕМ ({len(acc_names)})")
        else:
            self.stdout.write(f"  • Счета Express ({len(acc_names)}):        {', '.join(acc_names) or '—'}")

        if not confirm:
            self.stdout.write(self.style.WARNING(
                "\nDRY-RUN: ничего не удалено. Для реального удаления добавьте --confirm"
            ))
            return

        # Порядок важен: операции ссылаются на счета через PROTECT.
        transfers.delete()
        sales.delete()
        expenses.delete()
        if not keep_accounts:
            express_accounts.delete()

        self.stdout.write(self.style.SUCCESS(
            f"\n✔ Удалено: продаж {n_sales}, расходов {n_exp}, переводов {n_tr}"
            + ("" if keep_accounts else f", счетов {len(acc_names)}")
        ))
        self.stdout.write(self.style.SUCCESS("Готово. Данные Loko Express очищены."))
