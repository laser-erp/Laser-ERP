# Убран help_text у allocate_cost

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0035_alter_techcard_name"),
    ]

    operations = [
        migrations.AlterField(
            model_name="techcard",
            name="allocate_cost",
            field=models.BooleanField(
                blank=True,
                null=True,
                verbose_name="Распределять себестоимость",
            ),
        ),
    ]
