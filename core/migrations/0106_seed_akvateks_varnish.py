from django.db import migrations

# Паркетный акриловый лак Akvateks (Лемана): бесцветный, три степени блеска.
# Банный Sauna и покрытие «Акватекс 2в1» (цветное, не лак) не заводим.
VARNISH_NAMES = (
    "Лак акриловый Акватекс «матовый»",
    "Лак акриловый Акватекс «полуматовый»",
    "Лак акриловый Акватекс «глянцевый»",
)


def seed_akvateks_varnish(apps, schema_editor):
    MaterialGroup = apps.get_model("core", "MaterialGroup")
    MaterialGroupType = apps.get_model("core", "MaterialGroupType")
    Material = apps.get_model("core", "Material")

    group = None
    for existing in MaterialGroup.objects.all():
        name_n = (existing.name or "").casefold().replace("ё", "е")
        if "покрыт" in name_n:
            group = existing
            break
    if group is None:
        group = MaterialGroup.objects.create(
            name="Покрытия",
            has_grade=False,
            has_sheet_size=False,
        )

    MaterialGroupType.objects.get_or_create(
        group=group,
        name="лак акриловый",
        defaults={"sort_order": 2},
    )

    for name in VARNISH_NAMES:
        Material.objects.get_or_create(
            name=name,
            defaults={
                "group": group,
                "material_type": "лак акриловый",
                "unit": "л",
            },
        )


def unseed_akvateks_varnish(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    Material.objects.filter(name__in=VARNISH_NAMES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0105_seed_more_stain_brands"),
    ]

    operations = [
        migrations.RunPython(seed_akvateks_varnish, unseed_akvateks_varnish),
    ]
