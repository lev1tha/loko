from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Application user with a role-based access model.

    Roles:
      * ADMIN    — full access, may edit dynamic cost price and settings.
      * MANAGER  — cashier/manager: registers sales, expenses, transfers; sees reports.
      * DIRECTOR — «Директор»: read-only. Sees ONLY the ОПиУ/ОДДС reports of his own
                   direction (``module``); cannot add or edit anything anywhere.
      * OPERATOR — «Сотрудник»: data-entry only. May ONLY add Loko Express sales;
                   has NO access to any financial data, reports or other modules.
    """

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Администратор"
        MANAGER = "MANAGER", "Кассир/Менеджер"
        DIRECTOR = "DIRECTOR", "Директор"
        OPERATOR = "OPERATOR", "Сотрудник"
        WAREHOUSE = "WAREHOUSE", "Складовщик"

    class Direction(models.TextChoices):
        EXPRESS = "EXPRESS", "Loko Express"
        BUSINESS = "BUSINESS", "Loko Business"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MANAGER,
        verbose_name="Роль",
    )
    # Направление директора (Express / Business). Только для роли DIRECTOR —
    # ограничивает, чьи отчёты ОПиУ/ОДДС он видит. У остальных ролей пусто.
    module = models.CharField(
        max_length=10,
        choices=Direction.choices,
        blank=True,
        null=True,
        verbose_name="Направление (для директора)",
    )
    # Филиал сотрудника (Loko Express). Продажи оператора авто-тегируются им;
    # без него оператор не может создать продажу (guard-400 во views).
    branch = models.ForeignKey(
        "finance.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
        verbose_name="Филиал (для сотрудника)",
    )

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_director(self) -> bool:
        """«Директор» — read-only доступ к отчётам своего направления.

        A superuser is never treated as a director (full access wins).
        """
        return self.role == self.Role.DIRECTOR and not self.is_superuser

    @property
    def is_operator(self) -> bool:
        """«Сотрудник» — только ввод продаж Express, без доступа к финансам.

        A superuser is never treated as an operator (full access wins).
        """
        return self.role == self.Role.OPERATOR and not self.is_superuser

    @property
    def is_warehouse(self) -> bool:
        """«Складовщик» — только складской модуль (сборка/выдача) своего филиала;
        без доступа к финансам, отчётам и продажам.

        A superuser is never treated as a warehouse worker (full access wins).
        """
        return self.role == self.Role.WAREHOUSE and not self.is_superuser

    def __str__(self) -> str:
        return f"{self.username} ({self.get_role_display()})"
