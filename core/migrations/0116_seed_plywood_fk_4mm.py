from decimal import Decimal

from django.db import migrations

# Те же три формата, что у 3 мм / 6 мм. Имена как у карточек 3 мм.
PLYWOOD_4MM = (
    {
        "name": "Фанера ФК 900*600 сорт 2/2 4мм",
        "length": Decimal("900"),
        "width": Decimal("600"),
    },
    {
        "name": "Фанера ФК 621*621 сорт 2/2 4мм",
        "length": Decimal("621"),
        "width": Decimal("621"),
    },
    {
        "name": "Фанера ФК 317*900 сорт 2/2 4мм",
        "length": Decimal("900"),
        "width": Decimal("317"),
    },
)


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


def seed_plywood_4mm(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    MaterialGroupType = apps.get_model("core", "MaterialGroupType")
    group = _new_sheet_group(apps)
    MaterialGroupType.objects.get_or_create(
        group=group,
        name="Фанера ФК",
        defaults={"sort_order": 0},
    )
    for row in PLYWOOD_4MM:
        Material.objects.get_or_create(
            name=row["name"],
            defaults={
                "group": group,
                "material_type": "Фанера ФК",
                "unit": "лист",
                "sheet_length_mm": row["length"],
                "sheet_width_mm": row["width"],
                "thickness_mm": Decimal("4"),
            },
        )


def unseed_plywood_4mm(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    Material.objects.filter(name__in=[row["name"] for row in PLYWOOD_4MM]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0115_rename_kr_acrylic_primer"),
    ]

    operations = [
        migrations.RunPython(seed_plywood_4mm, unseed_plywood_4mm),
    ]
