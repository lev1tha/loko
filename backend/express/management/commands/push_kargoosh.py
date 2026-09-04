"""Отправить в Kargoosh (MySQL сайта) продажи Loko, ожидающие синхронизации.

    python manage.py push_kargoosh            # всё, что помечено kargo_sync_pending
    python manage.py push_kargoosh --dry-run  # показать, что ушло бы, без записи

Обычно не нужен отдельно: ``import_kargoosh --incremental`` делает это перед
импортом, а при KARGO_PUSH_IMMEDIATE продажи уходят сразу при сохранении.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from express import kargo_push


class Command(BaseCommand):
    help = "Loko → Kargoosh: отправить ожидающие продажи в таблицу orders сайта."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=500)

    def handle(self, *args, **opts):
        if not kargo_push.enabled():
            raise CommandError("KARGO_DB_HOST не задан — мост выключен.")
        qs = kargo_push.pending_qs()[: opts["limit"]]
        if opts["dry_run"]:
            for s in qs:
                row = kargo_push.sale_row(s, {}, settings.KARGO_DEFAULT_ADMIN_ID)
                self.stdout.write(f"  #{s.id} {s.client_code} → {row and (row['s_tracking_number'], row['i_status'], row['i_weight'], row['i_price'])}")
            self.stdout.write(f"ожидают: {qs.count()} (dry-run, ничего не отправлено)")
            return
        stats = kargo_push.push_pending(limit=opts["limit"])
        self.stdout.write(f"Loko → Kargoosh: {stats}")
        if stats.get("error"):
            raise CommandError("MySQL Kargoosh недоступен: " + stats["error"])
