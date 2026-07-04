# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0075_techcarditem_composition_order"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="vat_rate_percent",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Ставка НДС в процентах (например 20 или 10).",
                max_digits=5,
                null=True,
                verbose_name="НДС",
            ),
        ),
    ]
