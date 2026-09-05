"""Склеить клиентов-дублей по телефону и привести номера к единому формату.

До унификации QR-страница сохраняла номер как ввёл клиент («996700123456»), а
импорт Kargoosh — 9 цифр («700123456»): один человек — два клиента. Команда:
  1) приводит все телефоны к каноническому виду (Client.normalize_phone);
  2) группы с одинаковым каноническим номером склеивает в одного клиента —
     приоритет у аккаунта с сайта (legacy_kargo_id), иначе у самого старого;
     заявки, оценки и пустые поля переносятся, дубли удаляются.

    python manage.py merge_duplicate_clients --dry-run
    python manage.py merge_duplicate_clients
"""
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from express.models import Client, EmployeeRating, WarehouseOrder

MERGE_FIELDS = ("name", "last_name", "email", "code", "password_hash", "pass_code", "pass_date", "tg_id",
                "branch", "discount", "reg_date", "access_date", "access_ip", "legacy_kargo_id")


class Command(BaseCommand):
    help = "Склеить клиентов-дублей по телефону (QR «+996…» против «700…» из Kargoosh)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        groups = defaultdict(list)
        for c in Client.objects.all().order_by("id"):
            groups[Client.normalize_phone(c.phone) or c.phone].append(c)
        merged = renamed = 0
        with transaction.atomic():
            for canon, clients in groups.items():
                if len(clients) > 1:
                    clients.sort(key=lambda c: (c.legacy_kargo_id is None, c.id))  # сайт первым, потом старший
                    keeper, dups = clients[0], clients[1:]
                    for d in dups:
                        self.stdout.write(f"  {canon}: {keeper.phone}#{keeper.id} ← {d.phone}#{d.id} ({d.name or '—'}, заявок {d.orders.count()})")
                        if dry:
                            continue
                        WarehouseOrder.objects.filter(client=d).update(client=keeper)
                        for r in EmployeeRating.objects.filter(client=d):
                            if EmployeeRating.objects.filter(client=keeper, employee=r.employee).exists():
                                r.delete()
                            else:
                                r.client = keeper
                                r.save(update_fields=["client"])
                        for f in MERGE_FIELDS:
                            if not getattr(keeper, f) and getattr(d, f):
                                setattr(keeper, f, getattr(d, f))
                        d.delete()
                        merged += 1
                    if not dry:
                        keeper.save()
                    clients = [keeper]
                c = clients[0]
                if c.phone != canon:
                    renamed += 1
                    if not dry:
                        c.phone = canon
                        c.save(update_fields=["phone", "updated_at"])
            if dry:
                transaction.set_rollback(True)
        mode = "DRY-RUN" if dry else "записано"
        self.stdout.write(self.style.SUCCESS(f"Склеено дублей: {merged}, приведено номеров к формату: {renamed} ({mode})."))
