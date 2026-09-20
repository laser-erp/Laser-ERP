# На этапе «Лазерная резка» — только метры, без материала в строке

from django.db import migrations


def _laser_cut_stage_ids(ProductionStage):
    ids = []
    for pk, name in ProductionStage.objects.values_list("pk", "name"):
        n = (name or "").lower().replace("ё", "е")
        if "лазер" in n and "рез" in n and "гравир" not in n:
            ids.append(pk)
    return ids


def strip_material_on_laser_cut(apps, schema_editor):
    ProductionStage = apps.get_model("core", "ProductionStage")
    TechCardItem = apps.get_model("core", "TechCardItem")
    stage_ids = _laser_cut_stage_ids(ProductionStage)
    if not stage_ids:
        return
    for item in TechCardItem.objects.filter(production_stage_id__in=stage_ids):
        cl = item.cut_length_meters_per_unit
        if cl is None or cl <= 0:
            continue
        changed = False
        if item.material_id:
            item.material_id = None
            changed = True
        if item.product_id:
            item.product_id = None
            changed = True
        if item.quantity and item.quantity != 0:
            item.quantity = 0
            changed = True
        if changed:
            item.save(update_fields=["material_id", "product_id", "quantity"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0134_tablichka_laser_cut_norm"),
    ]

    operations = [
        migrations.RunPython(strip_material_on_laser_cut, noop),
    ]
