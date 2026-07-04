# Группа техкарты (FK на ProductGroup)

import django.db.models.deletion
from django.db import migrations, models


def copy_group_from_product(apps, schema_editor):
    TechCard = apps.get_model("core", "TechCard")
    Product = apps.get_model("core", "Product")
    for tc in TechCard.objects.filter(product_id__isnull=False).iterator():
        if tc.card_group_id:
            continue
        pg_id = (
            Product.objects.filter(pk=tc.product_id)
            .values_list("product_group_id", flat=True)
            .first()
        )
        if pg_id:
            TechCard.objects.filter(pk=tc.pk).update(card_group_id=pg_id)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0036_techcard_allocate_cost_clear_help"),
    ]

    operations = [
        migrations.AddField(
            model_name="techcard",
            name="card_group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tech_cards",
                to="core.productgroup",
                verbose_name="Группа техкарты",
            ),
        ),
        migrations.RunPython(copy_group_from_product, noop_reverse),
    ]
