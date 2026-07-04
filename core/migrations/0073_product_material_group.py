# Generated manually for Product.material_group

import django.db.models.deletion
from django.db import migrations, models


def copy_material_product_groups_to_material_group(apps, schema_editor):
    Product = apps.get_model("core", "Product")
    MaterialGroup = apps.get_model("core", "MaterialGroup")
    ProductGroup = apps.get_model("core", "ProductGroup")
    name_to_mg = {(mg.name or "").strip().lower(): mg.pk for mg in MaterialGroup.objects.all()}
    for p in Product.objects.filter(product_kind="material").exclude(product_group_id=None):
        try:
            pg = ProductGroup.objects.get(pk=p.product_group_id)
        except ProductGroup.DoesNotExist:
            continue
        key = (pg.name or "").strip().lower()
        mid = name_to_mg.get(key)
        if mid:
            p.material_group_id = mid
            p.product_group_id = None
            p.save(update_fields=["material_group_id", "product_group_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0072_techcarditem_component_tech_card"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="material_group",
            field=models.ForeignKey(
                blank=True,
                help_text="Только для вида «Материал»: та же классификация, что у складского справочника материалов.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="products_as_material_nomenclature",
                to="core.materialgroup",
                verbose_name="Группа материалов",
            ),
        ),
        migrations.RunPython(copy_material_product_groups_to_material_group, migrations.RunPython.noop),
    ]
