from decimal import Decimal

from django.conf import settings as dj_settings
from django.db import models

from finance.models import Account, Currency, Expense, ExpenseCategory


class Deposit(models.Model):
    """A deposit received in the Loko Business direction.

    Deposits are NOT revenue automatically. They sit as HELD until an
    explicit «Признать как выручку» (→ RECOGNIZED) command. If forwarded to a
    supplier as a prepayment, a SUPPLIER expense is created at that moment and
    the deposit is marked SENT_SUPPLIER.
    """

    class Status(models.TextChoices):
        HELD = "HELD", "Принят (не признан)"
        RECOGNIZED = "RECOGNIZED", "Признан как выручка"
        SENT_SUPPLIER = "SENT_SUPPLIER", "Отправлен поставщику"

    source = models.CharField(max_length=160, verbose_name="Источник / клиент")
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="deposits",
        verbose_name="Счёт зачисления",
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Сумма")
    currency = models.CharField(
        max_length=3, choices=Currency.choices, default=Currency.KGS, verbose_name="Валюта"
    )
    status = models.CharField(
        max_length=14, choices=Status.choices, default=Status.HELD, verbose_name="Статус"
    )
    note = models.CharField(max_length=255, blank=True, verbose_name="Комментарий")
    date = models.DateField(verbose_name="Дата")
    recognized_date = models.DateField(null=True, blank=True, verbose_name="Дата признания выручки")
    created_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deposits",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Депозит"
        verbose_name_plural = "Депозиты"
        ordering = ("-date", "-id")

    def save(self, *args, **kwargs):
        # Currency always follows the account it lands on.
        if self.account_id:
            self.currency = self.account.currency
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.source}: {self.amount} {self.currency} [{self.get_status_display()}]"

    def recognize_as_revenue(self, when=None):
        self.status = self.Status.RECOGNIZED
        self.recognized_date = when or self.date
        self.save(update_fields=["status", "recognized_date"])

    def send_to_supplier(self, when=None, supplier=None):
        """Forward the held deposit to a supplier as a prepayment (an expense)."""
        Expense.objects.create(
            account=self.account,
            category=ExpenseCategory.SUPPLIER,
            amount=self.amount,
            description=f"Предоплата поставщику{(' ' + supplier) if supplier else ''} "
            f"(депозит #{self.pk} от {self.source})",
            date=when or self.date,
            created_by=self.created_by,
        )
        self.status = self.Status.SENT_SUPPLIER
        self.save(update_fields=["status"])


class Debt(models.Model):
    """Кредиторская (payable) / Дебиторская (receivable) задолженность."""

    class Kind(models.TextChoices):
        PAYABLE = "PAYABLE", "Кредиторская (мы должны)"
        RECEIVABLE = "RECEIVABLE", "Дебиторская (нам должны)"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Открыта"
        CLOSED = "CLOSED", "Погашена"

    kind = models.CharField(max_length=12, choices=Kind.choices, verbose_name="Тип")
    counterparty = models.CharField(max_length=160, verbose_name="Контрагент")
    amount = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Сумма")
    currency = models.CharField(
        max_length=3, choices=Currency.choices, default=Currency.CNY, verbose_name="Валюта"
    )
    status = models.CharField(
        max_length=8, choices=Status.choices, default=Status.OPEN, verbose_name="Статус"
    )
    note = models.CharField(max_length=255, blank=True, verbose_name="Комментарий")
    date = models.DateField(verbose_name="Дата")
    created_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="debts",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Задолженность"
        verbose_name_plural = "Задолженности"
        ordering = ("-date", "-id")

    def __str__(self) -> str:
        return f"{self.get_kind_display()} — {self.counterparty}: {self.amount} {self.currency}"
