# Этап позиции техкарты (из техпроцесса)

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0037_techcard_card_group"),
    ]

    operations = [
        migrations.AddField(
            model_name="techcarditem",
            name="production_stage",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tech_card_items",
                to="core.productionstage",
                verbose_name="Этап",
            ),
        ),
    ]
