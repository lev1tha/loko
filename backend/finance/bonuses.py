"""Расчёт месячных бонусов сотрудников (KPI-система «внутрянки»).

Итог за месяц складывается из 7 частей (тарифы заданы клиентом):
  1. Оклад                     — базовый (по умолчанию 20 000).
  2. Дисциплина                — 2 000, если соблюдена.
  3. Проверка (тайный клиент)  — по баллу 1–5: 3→1000, 4→1500, 4.5→2000, 5→2500 (1–2 → замечание, 0).
  4. Оборот (кг филиала/мес)   — 3000→2000, 4000→3000, 5000→5000, 7000→8000, 10000→12000.
  5. Звёзды от клиентов        — 3→2000, 4→3500, 4.5→4500, 5→6000 (1–2 → замечание, 0).
  6. Стаж (месяцев)            — 3–6→1000, 6–12→2000, 12–18→3000, 18+→3500.
  7. Отзывы (2ГИС/Instagram)   — 200 за каждый.

Оборот и стаж считаются из данных; оклад/дисциплина/проверка/отзывы — ручные;
звёзды пока ручные (авто-подтянутся, когда подключим клиентскую оценку).
"""
from datetime import date
from decimal import Decimal

from django.db.models import Sum

DEFAULT_OKLAD = Decimal("20000")
DISCIPLINE_BONUS = Decimal("2000")
REVIEW_EACH = Decimal("200")

# Пороговые тарифы (по возрастанию порога) — берём наибольший достигнутый.
INSPECTION_TIERS = [(3, Decimal("1000")), (4, Decimal("1500")), (Decimal("4.5"), Decimal("2000")), (5, Decimal("2500"))]
STARS_TIERS = [(3, Decimal("2000")), (4, Decimal("3500")), (Decimal("4.5"), Decimal("4500")), (5, Decimal("6000"))]
TURNOVER_TIERS = [(3000, Decimal("2000")), (4000, Decimal("3000")), (5000, Decimal("5000")), (7000, Decimal("8000")), (10000, Decimal("12000"))]
TENURE_TIERS = [(3, Decimal("1000")), (6, Decimal("2000")), (12, Decimal("3000")), (18, Decimal("3500"))]

BONUS_ROLES = ("OPERATOR", "WAREHOUSE", "MANAGER")


def tier_bonus(value, tiers) -> Decimal:
    """Наибольший бонус, чей порог достигнут (иначе 0). ``value=None`` → 0."""
    result = Decimal("0")
    if value is None:
        return result
    for threshold, bonus in tiers:
        if value >= threshold:
            result = bonus
    return result


def _period_range(period: str):
    """'YYYY-MM' → (первое число месяца, первое число следующего)."""
    year, month = (int(x) for x in period.split("-"))
    start = date(year, month, 1)
    end = date(year + (month // 12), (month % 12) + 1, 1)
    return start, end, year, month


def _turnover_by_branch(start, end):
    """Оборот в кг за месяц по филиалам (из оприходованных продаж Express)."""
    from express.models import Sale
    rows = (
        Sale.objects.filter(account__module="EXPRESS", date__gte=start, date__lt=end)
        .values("branch_id").annotate(kg=Sum("weight_kg"))
    )
    by_branch, total = {}, Decimal("0")
    for r in rows:
        kg = r["kg"] or Decimal("0")
        by_branch[r["branch_id"]] = kg
        total += kg
    return by_branch, total


def build_bonuses(period: str):
    """Список бонусов всех сотрудников за месяц ``period`` (YYYY-MM).

    Для каждого сотрудника берёт/создаёт строку ручных значений (EmployeeBonus),
    добавляет расчётные (оборот филиала, стаж) и считает итог по тарифам.
    """
    from django.contrib.auth import get_user_model
    from .models import EmployeeBonus

    User = get_user_model()
    start, end, year, month = _period_range(period)
    by_branch, total_kg = _turnover_by_branch(start, end)

    employees = (
        User.objects.filter(role__in=BONUS_ROLES, is_active=True)
        .select_related("branch").order_by("branch_id", "username")
    )
    out = []
    for emp in employees:
        row, _ = EmployeeBonus.objects.get_or_create(employee=emp, period=period)
        # Оборот: филиал сотрудника; без филиала (напр. менеджер) — общий по компании.
        branch_kg = by_branch.get(emp.branch_id) if emp.branch_id else total_kg
        branch_kg = branch_kg or Decimal("0")
        # Стаж в месяцах на конец периода (по дате создания аккаунта).
        joined = emp.date_joined.date() if hasattr(emp.date_joined, "date") else emp.date_joined
        months = (year - joined.year) * 12 + (month - joined.month)
        months = max(months, 0)

        parts = {
            "oklad": row.oklad,
            "discipline": DISCIPLINE_BONUS if row.discipline_ok else Decimal("0"),
            "inspection": tier_bonus(row.inspection_score, INSPECTION_TIERS),
            "turnover": tier_bonus(branch_kg, TURNOVER_TIERS),
            "stars": tier_bonus(row.stars, STARS_TIERS),
            "tenure": tier_bonus(months, TENURE_TIERS),
            "reviews": REVIEW_EACH * row.reviews_count,
        }
        total = sum(parts.values(), Decimal("0"))
        out.append({
            "id": row.id,
            "employee": emp.id,
            "employee_name": emp.get_full_name() or emp.username,
            "role": emp.role,
            "role_display": emp.get_role_display(),
            "branch_name": emp.branch.name if emp.branch_id else None,
            "period": period,
            # входные (редактируемые менеджером)
            "oklad": row.oklad,
            "discipline_ok": row.discipline_ok,
            "inspection_score": row.inspection_score,
            "stars": row.stars,
            "reviews_count": row.reviews_count,
            "note": row.note,
            # расчётные
            "turnover_kg": branch_kg,
            "tenure_months": months,
            "parts": parts,
            "total": total,
        })
    return out
