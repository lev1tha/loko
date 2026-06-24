"""Bootstrap Loko Express with initial data.

Creates:
  * an admin user (admin / admin123) and a manager (kassir / kassir123)
  * the three default accounts: Наличные, Оптима Банк, МБанк
  * the singleton settings row with default pricing/cost
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from finance.models import Account, AppSettings

User = get_user_model()


class Command(BaseCommand):
    help = "Seed initial users, accounts and settings for Loko Express."

    def handle(self, *args, **options):
        # Settings singleton
        AppSettings.load()
        self.stdout.write(self.style.SUCCESS("✔ Настройки инициализированы"))

        # Users
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser(
                username="admin",
                password="admin123",
                role=User.Role.ADMIN,
            )
            self.stdout.write(self.style.SUCCESS("✔ Создан администратор: admin / admin123"))

        if not User.objects.filter(username="kassir").exists():
            u = User(username="kassir", role=User.Role.MANAGER)
            u.set_password("kassir123")
            u.save()
            self.stdout.write(self.style.SUCCESS("✔ Создан кассир: kassir / kassir123"))

        # Loko Express accounts (all KGS)
        express_accounts = [
            ("Наличные", Account.Kind.CASH, "KGS"),
            ("Оптима Банк", Account.Kind.BANK, "KGS"),
            ("МБанк", Account.Kind.BANK, "KGS"),
        ]
        for name, kind, currency in express_accounts:
            _, created = Account.objects.get_or_create(
                name=name,
                defaults={"kind": kind, "currency": currency, "module": "EXPRESS"},
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"✔ Express счёт: {name}"))

        # Loko Business accounts — мультивалютные кошельки/банки (реальные данные).
        business_accounts = [
            ("Вичат", "CNY", "BANK", Decimal("20187")),
            ("Алипей", "CNY", "BANK", Decimal("19192")),
            ("Мбанк (Business)", "KGS", "BANK", Decimal("0")),
            ("ICBC", "CNY", "BANK", Decimal("8397")),
            ("ICBC 0687", "CNY", "BANK", Decimal("4622")),
            ("9148 карта", "CNY", "BANK", Decimal("0")),
            ("Наличные юань", "CNY", "CASH", Decimal("0")),
        ]
        for name, currency, kind, initial in business_accounts:
            _, created = Account.objects.get_or_create(
                name=name,
                defaults={
                    "kind": kind,
                    "currency": currency,
                    "module": "BUSINESS",
                    "initial_balance": initial,
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"✔ Business счёт: {name} ({currency})"))

        self.stdout.write(self.style.SUCCESS("Готово. Данные Loko (Express + Business) загружены."))
