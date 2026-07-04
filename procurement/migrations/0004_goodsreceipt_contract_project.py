# Generated manually for UI «Приёмка»

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("procurement", "0003_supplier_po_lines_and_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="goodsreceipt",
            name="contract",
            field=models.CharField(blank=True, max_length=255, verbose_name="Договор"),
        ),
        migrations.AddField(
            model_name="goodsreceipt",
            name="project",
            field=models.CharField(blank=True, max_length=255, verbose_name="Проект"),
        ),
    ]
