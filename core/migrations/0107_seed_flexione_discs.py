from django.db import migrations

# Недостающие круги 125 мм (P100/P120/P180 уже в базе, не трогаем).
DISC_NAMES = (
    "Круг шлифовальный FLEXIONE 125мм 8 отв. (P150)",
    "Круг шлифовальный FLEXIONE 125мм 8 отв. (P220)",
    "Круг шлифовальный FLEXIONE 125мм 8 отв. (P240)",
    "Круг шлифовальный FLEXIONE 125мм 8 отв. (P280)",
    "Круг шлифовальный FLEXIONE 125мм 8 отв. (P320)",
    "Круг шлифовальный ABRAFORCE 125мм 8 отв. (P400)",
)


def seed_discs(apps, schema_editor):
    MaterialGroup = apps.get_model("core", "MaterialGroup")
    Material = apps.get_model("core", "Material")

    group = None
    for existing in MaterialGroup.objects.all():
        name_n = (existing.name or "").casefold().replace("ё", "е")
        if "абразив" in name_n:
            group = existing
            break
    if group is None:
        group = MaterialGroup.objects.create(
            name="Абразивы",
            has_grade=False,
            has_sheet_size=False,
        )
    else:
        group.has_grade = False
        group.has_sheet_size = False
        group.save(update_fields=["has_grade", "has_sheet_size"])

    for name in DISC_NAMES:
        Material.objects.get_or_create(
            name=name,
            defaults={
                "group": group,
                "unit": "шт",
                "material_type": "",
            },
        )


def unseed_discs(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    Material.objects.filter(name__in=DISC_NAMES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0106_seed_akvateks_varnish"),
    ]

    operations = [
        migrations.RunPython(seed_discs, unseed_discs),
    ]
