from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0119_primer_production_costs"),
    ]

    operations = [
        migrations.AddField(
            model_name="material",
            name="purchase_price",
            field=models.DecimalField(
                blank=True,
                decimal_places=4,
                help_text=(
                    "Цена за единицу с чека или счёта. Пока нет проведённых приёмок, "
                    "техкарта и себестоимость берут эту цену. После приёмки — средняя по поступлениям."
                ),
                max_digits=14,
                null=True,
                verbose_name="Закупочная цена",
            ),
        ),
    ]
