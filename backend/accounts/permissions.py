from rest_framework.permissions import BasePermission, SAFE_METHODS


def _is_operator(user) -> bool:
    return bool(user and user.is_authenticated and getattr(user, "is_operator", False))


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

    message = "Недостаточно прав: раздел недоступен для роли «Сотрудник»."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and not _is_operator(user))


class SalesAccess(BasePermission):
    """Sales endpoint access.

    * Admin / Manager — full access (list, edit, delete, summary, …).
    * Operator («Сотрудник») — may ONLY create a sale, request a price quote
      and read the minimal Express-account picker. No list / edit / delete /
      summary, so no financial figures (revenue, margin, debtors) are exposed.
    """

    message = "Сотрудник может только добавлять продажи."

    # ViewSet actions an operator is allowed to perform.
    OPERATOR_ACTIONS = frozenset({"create", "quote", "express_accounts"})

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if _is_operator(user):
            return getattr(view, "action", None) in self.OPERATOR_ACTIONS
        return True
