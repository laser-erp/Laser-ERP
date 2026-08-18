from decimal import Decimal

from django.db import migrations

NAME = "Фанера ФК 621×621 сорт 2/2 3 мм"
OLD_NAMES = (NAME, "Фанера ФК 621*621 сорт 2/2 3мм")


def _new_sheet_group(apps):
    MaterialGroup = apps.get_model("core", "MaterialGroup")
    for existing in MaterialGroup.objects.all():
        name_n = (existing.name or "").casefold().replace("ё", "е")
        if name_n == "лист новый":
            return existing
    return MaterialGroup.objects.create(
        name="Лист новый",
        has_grade=False,
        has_sheet_size=True,
    )


def ensure_621_3mm_sheet(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    MaterialGroupType = apps.get_model("core", "MaterialGroupType")
    material = None
    for name in OLD_NAMES:
        material = Material.objects.filter(name=name).first()
        if material is not None:
            break
    group = _new_sheet_group(apps)
    MaterialGroupType.objects.get_or_create(
        group=group,
        name="Фанера ФК",
        defaults={"sort_order": 0},
    )
    fields = {
        "name": NAME,
        "group": group,
        "material_type": "Фанера ФК",
        "unit": "лист",
        "sheet_length_mm": Decimal("621"),
        "sheet_width_mm": Decimal("621"),
        "thickness_mm": Decimal("3"),
        "grade": "2/2",
    }
    if material is None:
        Material.objects.create(**fields)
        return
    Material.objects.filter(pk=material.pk).update(
        name=NAME,
        sheet_length_mm=Decimal("621"),
        sheet_width_mm=Decimal("621"),
        thickness_mm=Decimal("3"),
        grade="2/2",
    )


def noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0123_seed_fk_621x621_goods"),
    ]

    operations = [
        migrations.RunPython(ensure_621_3mm_sheet, noop_reverse),
    ]
