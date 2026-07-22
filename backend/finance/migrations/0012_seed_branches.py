"""Сид двух филиалов Loko Express (реф-данные из ТЗ).

Идемпотентно (get_or_create по имени). Историю операций НЕ трогаем — она
остаётся с branch=NULL. Reverse — no-op: реф-данные не удаляем при откате
(и не упираемся в PROTECT, если к филиалу уже привязаны операции).
"""

from django.db import migrations

BRANCHES = [
    ("Loko Express — Гульчинская улица, 13/1", "Гульчинская улица, 13/1"),
    ("Loko Express — Исхака Раззакова, 40", "Исхака Раззакова, 40"),
]


def seed_branches(apps, schema_editor):
    Branch = apps.get_model("finance", "Branch")
    for name, address in BRANCHES:
        Branch.objects.get_or_create(name=name, defaults={"address": address})


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0011_branch_expense_branch_otherincome_branch_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_branches, migrations.RunPython.noop),
    ]
