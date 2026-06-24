from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Application user with a role-based access model.

    Two roles for the first module:
      * ADMIN   — full access, may edit dynamic cost price and settings.
      * MANAGER — cashier/manager: registers sales, expenses, transfers.
    """

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Администратор"
        MANAGER = "MANAGER", "Кассир/Менеджер"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MANAGER,
        verbose_name="Роль",
    )

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN or self.is_superuser

    def __str__(self) -> str:
        return f"{self.username} ({self.get_role_display()})"
