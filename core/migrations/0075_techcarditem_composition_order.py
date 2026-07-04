# Generated manually for product-tab row order on tech card

from django.db import migrations, models


def backfill_composition_order(apps, schema_editor):
    TechCardItem = apps.get_model("core", "TechCardItem")
    KIND = "component"
    tc_ids = (
        TechCardItem.objects.filter(item_kind=KIND)
        .values_list("tech_card_id", flat=True)
        .distinct()
    )
    for tc_id in tc_ids:
        rows = list(
            TechCardItem.objects.filter(tech_card_id=tc_id, item_kind=KIND).order_by(
                "pk"
            )
        )
        for i, row in enumerate(rows):
            TechCardItem.objects.filter(pk=row.pk).update(composition_order=i)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0074_backfill_material_from_product_nomenclature"),
    ]

    operations = [
        migrations.AddField(
            model_name="techcarditem",
            name="composition_order",
            field=models.PositiveIntegerField(
                db_index=True,
                default=0,
                help_text="Для сортировки строк «Продукция» на техкарте; материалы не затрагиваются.",
                verbose_name="Порядок в списке комплектующих",
            ),
        ),
        migrations.RunPython(backfill_composition_order, migrations.RunPython.noop),
    ]
