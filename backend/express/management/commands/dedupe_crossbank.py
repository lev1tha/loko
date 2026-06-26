"""Зачёт кросс-банковской задвоенности Оптима→МБанк (Loko Express).

Переводы с карты Оптима (Нурбек) на наши МБанк-счета («MBANK по номеру телефона
996220105653/996776904207») приходят в МБанк как «Cash-in» — те же деньги
задвоены: расход в Оптиме + выручка в МБанк, хотя это один внутренний перевод.

Оформляем такую пару как Transfer Оптима→МБанк (не выручка и не расход) и удаляем
обе задвоенные строки. Балансы счетов НЕ меняются (списание↔зачисление),
прибыль НЕ меняется, уходит только дутая выручка.

Запускать ПОСЛЕ import_mbank/import_optima. Идемпотентно: сначала удаляет свои
прежние авто-переводы (по метке), затем заново сопоставляет.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction as db_tx

from finance.models import Account, Expense, Transfer
from express.models import Sale

TAG = "Зачёт задвоения Оптима→МБанк (авто)"
OUR_PHONES = ("996220105653", "996776904207")  # Бектур, Каныкей


class Command(BaseCommand):
    help = "Зачёт кросс-банк задвоения: переводы Оптима→МБанк (приходят как Cash-in) → Transfer."

    @db_tx.atomic
    def handle(self, *args, **opts):
        try:
            optima = Account.objects.get(name="Оптима Банк")
            mbank = Account.objects.get(name="МБанк")
        except Account.DoesNotExist:
            self.stdout.write(self.style.ERROR("Счета «Оптима Банк»/«МБанк» не найдены — сначала импортируй банки."))
            return

        # Идемпотентность: убрать прежние авто-переводы этого зачёта.
        Transfer.objects.filter(from_account=optima, to_account=mbank, description=TAG).delete()

        # Оптима: исходящие на НАШИ mbank-телефоны («MBANK по номеру телефона …»).
        opt_out = [
            e for e in Expense.objects.filter(account=optima, created_by__isnull=True,
                                              description__icontains="MBANK по номеру")
            if any(p in e.description for p in OUR_PHONES)
        ]
        # МБанк: входящие cash-in (туда падают эти переводы).
        mb_in = list(Sale.objects.filter(account=mbank, created_by__isnull=True,
                                         client_code__icontains="cash"))

        used = set()
        made = 0
        total = Decimal("0")
        for e in sorted(opt_out, key=lambda x: -x.amount):
            for s in mb_in:
                if s.id in used:
                    continue
                if s.price_som == e.amount and abs((s.date - e.date).days) <= 3:
                    Transfer.objects.create(
                        from_account=optima, to_account=mbank,
                        amount=e.amount, to_amount=e.amount, rate=Decimal("1"),
                        date=e.date, description=TAG,
                    )
                    self.stdout.write(
                        f"  {e.amount:,.2f}: Оптима «{e.description[:32]}» ↔ МБанк «{s.client_code[:24]}» ({s.date})"
                    )
                    used.add(s.id)
                    s.delete()
                    e.delete()
                    made += 1
                    total += e.amount
                    break

        if made:
            self.stdout.write(self.style.SUCCESS(
                f"✔ Зачтено переводов Оптима→МБанк: {made} на {total:,.2f}; "
                f"удалено задвоенных строк: {made * 2} (продажи МБанк + расходы Оптима)."
            ))
            self.stdout.write("  Выручка снизилась на эту сумму, балансы и прибыль не изменились.")
        else:
            self.stdout.write("Совпадений не найдено (уже зачтено или нет таких операций).")
