# Generated manually: подпись поля «Наименование»

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0034_techcard_require_tech_process"),
    ]

    operations = [
        migrations.AlterField(
            model_name="techcard",
            name="name",
            field=models.CharField(max_length=255, verbose_name="Наименование"),
        ),
    ]
