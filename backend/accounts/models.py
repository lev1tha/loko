from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Application user with a role-based access model.

    Roles:
      * ADMIN    — full access, may edit dynamic cost price and settings.
      * MANAGER  — cashier/manager: registers sales, expenses, transfers; sees reports.
      * OPERATOR — «Сотрудник»: data-entry only. May ONLY add Loko Express sales;
                   has NO access to any financial data, reports or other modules.
    """

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Администратор"
        MANAGER = "MANAGER", "Кассир/Менеджер"
        OPERATOR = "OPERATOR", "Сотрудник"

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

    @property
    def is_operator(self) -> bool:
        """«Сотрудник» — только ввод продаж Express, без доступа к финансам.

        A superuser is never treated as an operator (full access wins).
        """
        return self.role == self.Role.OPERATOR and not self.is_superuser

    def __str__(self) -> str:
        return f"{self.username} ({self.get_role_display()})"
