from rest_framework.permissions import BasePermission, SAFE_METHODS


def _is_operator(user) -> bool:
    return bool(user and user.is_authenticated and getattr(user, "is_operator", False))


def _is_director(user) -> bool:
    return bool(user and user.is_authenticated and getattr(user, "is_director", False))


def _is_warehouse(user) -> bool:
    return bool(user and user.is_authenticated and getattr(user, "is_warehouse", False))


class IsAdmin(BasePermission):
    """Allow access only to administrators."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_admin)


class IsAdminOrReadOnly(BasePermission):
    """Everyone authenticated can read; only admins can write."""

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_admin


class DenyOperator(BasePermission):
    """Authenticated access for everyone EXCEPT the «Сотрудник» (operator) role.

    Operators are data-entry only and must never reach financial endpoints
    (reports, settings, accounts, expenses, transfers, deposits, debts, …).
    """

    message = "Недостаточно прав: раздел недоступен для этой роли."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated
            and not _is_operator(user)
            and not _is_warehouse(user)
        )


class DenyOperatorOrDirector(BasePermission):
    """Authenticated access for everyone EXCEPT «Сотрудник» (operator) and
    «Директор» (director).

    Directors are read-only and scoped to the ОПиУ/ОДДС reports of their own
    direction — they must never reach the data viewsets (accounts, expenses,
    transfers, deposits, debts, sales, settings, journal, balances, …).
    """

    message = "Недостаточно прав: раздел недоступен для этой роли."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and not _is_operator(user)
            and not _is_director(user)
            and not _is_warehouse(user)
        )


class SalesAccess(BasePermission):
    """Sales endpoint access — прямые продажи Express.

    * Admin / Manager — full access (list, edit, delete, summary, export, …).
    * Operator / Warehouse / Director — no access. В двухэтапном учёте оператор
      продажи напрямую НЕ создаёт: он формирует складскую заявку
      (``WarehouseItemViewSet`` / ``WarehouseOrderViewSet``), а продажа рождается
      при оприходовании складовщиком. Так операторам не видны финансовые цифры.
    """

    message = "Прямое ведение продаж доступно только кассиру/администратору."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if _is_director(user) or _is_warehouse(user) or _is_operator(user):
            return False
        return True


class WarehouseAccess(BasePermission):
    """Доступ к складскому модулю (заявки на сборку Loko Express).

    * Admin / Manager — полный доступ: создание, список всех филиалов, любые статусы
      (включая ISSUED «Выдано» после оплаты).
    * Warehouse («Складовщик») — только заявки СВОЕГО филиала: список/просмотр +
      смена статуса сборки (взять в работу / готово / отмена). Не «Выдаёт» (это
      кассир) и не создаёт заявки. Филиал и запрет ISSUED — на уровне вьюсета.
    * Operator («Сотрудник») — создать заявку и видеть заявки своего филиала.
    * Director — нет доступа.
    """

    message = "Недостаточно прав для складского модуля."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if _is_director(user):
            return False
        action = getattr(view, "action", None)
        if _is_warehouse(user):
            return action in {"list", "retrieve", "create", "status"}
        if _is_operator(user):
            return action in {"list", "retrieve", "create"}
        return True  # Manager / Admin — полный доступ


class WarehouseItemAccess(BasePermission):
    """Позиции складской заявки (двухэтапный учёт карго).

    * Складовщик — позиции СВОЕГО филиала: список/просмотр, оприходование
      (``receive`` / ``not_found`` / ``deliver``) и пикер счёта (``accounts``).
    * Оператор — СВОИ позиции: список (``mine``) и отправка не найденной в вечерний
      допоиск (``to_evening``). Финансовых цифр чужих позиций не видит.
    * Директор — нет доступа. Менеджер / админ — полный доступ.
    Фильтрация «только своё» — в ``get_queryset`` вьюсета (object-level).
    """

    message = "Недостаточно прав для позиций склада."

    WAREHOUSE_ACTIONS = {"list", "retrieve", "receive", "not_found", "deliver", "accounts"}
    OPERATOR_ACTIONS = {"mine", "to_evening"}

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if _is_director(user):
            return False
        action = getattr(view, "action", None)
        if _is_warehouse(user):
            return action in self.WAREHOUSE_ACTIONS
        if _is_operator(user):
            return action in self.OPERATOR_ACTIONS
        return True  # Manager / Admin — полный доступ


def _director_express(user) -> bool:
    """Директор направления Express (склад существует только в Express)."""
    return _is_director(user) and getattr(user, "module", None) == "EXPRESS"


class WorkflowAccess(BasePermission):
    """«Процесс работы» — прозрачность склада для директора: кто из сотрудников
    какие заказы обрабатывает, сколько кг/сом, что осталось на вечерний допоиск.

    * Admin / Manager — доступ.
    * Director — только направление Express (у Business склада нет).
    * Operator / Warehouse — нет (видят только своё через складской модуль).
    """

    message = "Недостаточно прав: раздел недоступен для этой роли."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if _is_operator(user) or _is_warehouse(user):
            return False
        if _is_director(user):
            return _director_express(user)
        return True


class StockAccess(BasePermission):
    """Остаток веса на складе (``WarehouseStock``).

    Единственное место, где директор ПИШЕТ: он ежедневно вносит приход кг на
    склад. Admin / Manager — тоже. Operator / Warehouse — нет. Удаление —
    админ или автор записи (проверка в вьюсете).
    """

    message = "Недостаточно прав: раздел недоступен для этой роли."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if _is_operator(user) or _is_warehouse(user):
            return False
        if _is_director(user):
            return _director_express(user)
        return True
