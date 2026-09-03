from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0016_account_legacy_kargo_card_id_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="branch",
            name="price_per_kg_som",
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=10, null=True,
                verbose_name="Цена за кг (сом) для Kargo-заказов филиала",
            ),
        ),
    ]
