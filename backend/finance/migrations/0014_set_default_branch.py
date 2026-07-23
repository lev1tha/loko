"""Назначить филиал по умолчанию — «Гульчинская, 13/1».

Подставляется в продажи без явно выбранного филиала (см. Branch.resolve_default).
Идемпотентно; reverse — no-op. Если по имени не найден (переименовали) — берём
первый по id, чтобы дефолт всегда существовал.
"""

from django.db import migrations

DEFAULT_NAME = "Loko Express — Гульчинская улица, 13/1"


def set_default(apps, schema_editor):
    Branch = apps.get_model("finance", "Branch")
    if Branch.objects.filter(name=DEFAULT_NAME).exists():
        Branch.objects.filter(name=DEFAULT_NAME).update(is_default=True)
        Branch.objects.exclude(name=DEFAULT_NAME).update(is_default=False)
    else:
        first = Branch.objects.order_by("id").first()
        if first:
            Branch.objects.filter(pk=first.pk).update(is_default=True)


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0013_branch_is_default"),
    ]

    operations = [
        migrations.RunPython(set_default, migrations.RunPython.noop),
    ]
