# Интеграция Kargo Osh, шаг 2: статус доставки/дата прибытия заказа, хеш пароля
# клиента (переименование — в Kargo это MD5, не bcrypt), журнал синхронизаций.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("express", "0012_client_access_date_client_access_ip_client_branch_and_more"),
    ]

    operations = [
        migrations.RenameField(
            model_name="client",
            old_name="password_bcrypt",
            new_name="password_hash",
        ),
        migrations.AlterField(
            model_name="client",
            name="password_hash",
            field=models.CharField(blank=True, max_length=128, verbose_name="Хеш пароля (из Kargo / Django)"),
        ),
        migrations.AddField(
            model_name="sale",
            name="arrival_date",
            field=models.DateField(blank=True, null=True, verbose_name="Дата прибытия на склад (Kargo)"),
        ),
        migrations.AddField(
            model_name="sale",
            name="delivery_status",
            field=models.CharField(
                blank=True,
                choices=[("TRANSIT", "В пути"), ("ARRIVED", "На складе"), ("DELIVERED", "Отдан")],
                db_index=True, max_length=10, null=True, verbose_name="Статус доставки (Kargo)",
            ),
        ),
        migrations.CreateModel(
            name="KargoSync",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mode", models.CharField(choices=[("FULL", "Полный импорт"), ("INCREMENTAL", "Инкремент"), ("RESCAN", "Полная сверка (upsert)")], max_length=12)),
                ("since", models.DateTimeField(blank=True, null=True, verbose_name="Окно с")),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("ok", models.BooleanField(default=False)),
                ("dry_run", models.BooleanField(default=False)),
                ("stats", models.JSONField(blank=True, default=dict)),
                ("error", models.TextField(blank=True)),
            ],
            options={
                "verbose_name": "Синхронизация Kargo",
                "verbose_name_plural": "Синхронизации Kargo",
                "ordering": ("-started_at",),
            },
        ),
    ]
