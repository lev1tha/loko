"""Bootstrap Loko (Express + Business) with initial data.

Creates:
  * an admin user and a manager user. Their passwords come from the
    ``SEED_ADMIN_PASSWORD`` / ``SEED_KASSIR_PASSWORD`` env vars. In DEBUG (dev)
    they fall back to the demo ``admin123`` / ``kassir123``. In production
    (DEBUG=False) without those env vars the users are created WITHOUT a usable
    password — set one with ``manage.py changepassword`` — so a publicly
    reachable API is never provisioned with guessable default credentials.
  * the three default Express accounts and the multi-currency Business accounts
  * the singleton settings row with default pricing/cost
"""

import os
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from finance.models import Account, AppSettings

User = get_user_model()


class Command(BaseCommand):
    help = "Seed initial users, accounts and settings for Loko (Express + Business)."

    def _password(self, env_name: str, demo: str):
        """Env password, or the demo one in DEBUG, or None (→ unusable) in prod."""
        return os.environ.get(env_name) or (demo if settings.DEBUG else None)

    def _make_user(self, username: str, role, env_name: str, demo: str, **extra):
        if User.objects.filter(username=username).exists():
            return
        password = self._password(env_name, demo)
        user = User(username=username, role=role, **extra)
        if password:
            user.set_password(password)
            hint = f"{username} / {demo}" if settings.DEBUG else f"{username} (пароль из {env_name})"
        else:
            user.set_unusable_password()
            hint = f"{username} (БЕЗ пароля — задайте: manage.py changepassword {username})"
        user.save()
        self.stdout.write(self.style.SUCCESS(f"✔ Пользователь: {hint}"))

    def handle(self, *args, **options):
        # Settings singleton
        AppSettings.load()
        self.stdout.write(self.style.SUCCESS("✔ Настройки инициализированы"))

        # Users (passwords from env; demo fallback only in DEBUG)
        self._make_user(
            "admin", User.Role.ADMIN, "SEED_ADMIN_PASSWORD", "admin123",
            is_staff=True, is_superuser=True,
        )
        self._make_user("kassir", User.Role.MANAGER, "SEED_KASSIR_PASSWORD", "kassir123")

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
