"""Закрепить заявки клиентов (QR) без сотрудника за сотрудником их точки — задним числом.

Раньше заявка, созданная клиентом по QR, оставалась без сотрудника, и продажи
после оприходования никому не засчитывались. Команда проходит по всем таким
заявкам и закрепляет их (и их продажи) за сотрудником филиала:

    python manage.py assign_client_orders --dry-run          # показать, что изменится
    python manage.py assign_client_orders                    # филиалы с ОДНИМ сотрудником — автоматически
    python manage.py assign_client_orders --branch 1 --operator eldos   # филиал с несколькими — вручную

Заявки филиалов, где сотрудников несколько или нет, без ``--branch/--operator``
не трогаются и перечисляются в отчёте.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from express.models import Sale, WarehouseItem, WarehouseOrder
from finance.models import Branch

User = get_user_model()


class Command(BaseCommand):
    help = "Закрепить заявки клиентов без сотрудника за сотрудником филиала (и их продажи)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Только показать, без записи.")
        parser.add_argument("--branch", type=int, help="Ограничить одним филиалом (id).")
        parser.add_argument("--operator", type=str, help="Логин сотрудника, за которым закрепить (вместе с --branch).")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        forced = None
        if opts["operator"]:
            if opts["branch"] is None:
                raise CommandError("--operator требует --branch.")
            forced = User.objects.filter(username=opts["operator"], is_active=True).first()
            if forced is None or not forced.is_operator:
                raise CommandError("Сотрудник не найден или его роль не «Сотрудник».")
            if forced.branch_id != opts["branch"]:
                raise CommandError("Сотрудник привязан к другому филиалу.")

        qs = WarehouseOrder.objects.filter(created_by__isnull=True).select_related("branch").order_by("branch_id", "id")
        if opts["branch"] is not None:
            qs = qs.filter(branch_id=opts["branch"])
        orders = list(qs)
        if not orders:
            self.stdout.write("Заявок без сотрудника нет.")
            return

        by_branch = {}
        for o in orders:
            by_branch.setdefault(o.branch, []).append(o)

        assigned_orders = assigned_sales = 0
        skipped = []
        with transaction.atomic():
            for branch, group in by_branch.items():
                operator = forced or WarehouseOrder.resolve_operator(branch)
                ops = list(WarehouseOrder.branch_operators(branch))
                if operator is None:
                    skipped.append((branch, len(group), ops))
                    continue
                ids = [o.id for o in group]
                sale_ids = list(WarehouseItem.objects.filter(order_id__in=ids, sale__isnull=False).values_list("sale_id", flat=True))
                self.stdout.write(f"  {branch}: {len(group)} заявок, {len(sale_ids)} продаж → {operator.get_full_name() or operator.username}")
                if not dry:
                    WarehouseOrder.objects.filter(id__in=ids).update(created_by=operator)
                    Sale.objects.filter(id__in=sale_ids, created_by__isnull=True).update(created_by=operator)
                assigned_orders += len(group)
                assigned_sales += len(sale_ids)
            if dry:
                transaction.set_rollback(True)

        for branch, n, ops in skipped:
            names = ", ".join(u.username for u in ops) or "нет сотрудников"
            self.stdout.write(self.style.WARNING(
                f"  {branch}: {n} заявок пропущено — сотрудников {len(ops)} ({names}). "
                f"Укажите явно: --branch {branch.id} --operator <логин>"
            ))
        mode = "DRY-RUN, ничего не записано" if dry else "записано"
        self.stdout.write(self.style.SUCCESS(f"Закреплено заявок: {assigned_orders}, продаж: {assigned_sales} ({mode})."))
