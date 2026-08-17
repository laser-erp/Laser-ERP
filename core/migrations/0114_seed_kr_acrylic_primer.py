import shutil
from pathlib import Path

from django.conf import settings
from django.db import migrations

PRIMER_NAME = "Грунт акриловый КР «глубокого проникновения»"
PRIMER_BRAND = "КР"
PHOTO_REL = "materials/primer_kr.png"
SEED_PHOTO = Path(__file__).resolve().parent.parent / "seed_media" / "primer_kr.png"


def _coatings_group(apps):
    MaterialGroup = apps.get_model("core", "MaterialGroup")
    for existing in MaterialGroup.objects.all():
        name_n = (existing.name or "").casefold().replace("ё", "е")
        if "покрыт" in name_n:
            return existing
    return MaterialGroup.objects.create(
        name="Покрытия",
        has_grade=False,
        has_sheet_size=False,
        has_brand=True,
        has_color=True,
    )


def _install_photo():
    if not SEED_PHOTO.exists():
        return ""
    dest_dir = Path(settings.MEDIA_ROOT) / "materials"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "primer_kr.png"
    shutil.copy2(SEED_PHOTO, dest)
    return PHOTO_REL


def seed_primer(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    MaterialGroupType = apps.get_model("core", "MaterialGroupType")
    MaterialGroupBrand = apps.get_model("core", "MaterialGroupBrand")

    group = _coatings_group(apps)
    MaterialGroupType.objects.get_or_create(
        group=group,
        name="грунт акриловый",
        defaults={"sort_order": 1},
    )
    MaterialGroupBrand.objects.get_or_create(
        group=group,
        name=PRIMER_BRAND,
        defaults={"sort_order": 60},
    )
    photo = _install_photo()
    material, created = Material.objects.get_or_create(
        name=PRIMER_NAME,
        defaults={
            "group": group,
            "material_type": "грунт акриловый",
            "brand": PRIMER_BRAND,
            "unit": "кг",
            "photo": photo,
        },
    )
    update = []
    if not created:
        if material.group_id != group.pk:
            material.group = group
            update.append("group")
        if material.material_type != "грунт акриловый":
            material.material_type = "грунт акриловый"
            update.append("material_type")
        if material.brand != PRIMER_BRAND:
            material.brand = PRIMER_BRAND
            update.append("brand")
        if material.unit != "кг":
            material.unit = "кг"
            update.append("unit")
    if photo and material.photo != photo:
        material.photo = photo
        update.append("photo")
    if update:
        material.save(update_fields=update)


def unseed_primer(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    Material.objects.filter(name=PRIMER_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0113_brand_help_text"),
    ]

    operations = [
        migrations.RunPython(seed_primer, unseed_primer),
    ]
