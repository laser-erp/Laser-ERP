from django.db import migrations

COATING_TYPES = (
    "морилка водная",
    "грунт акриловый",
    "лак акриловый",
)

STAIN_NAMES = (
    "Морилка водная Master Good «Дуб»",
    "Морилка водная Master Good «Орех»",
    "Морилка водная Master Good «Лиственница»",
    "Морилка водная Master Good «Сосна»",
    "Морилка водная Master Good «Мокко»",
    "Морилка водная Master Good «Эбеновое дерево»",
)


def seed_coatings(apps, schema_editor):
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
            description="Морилки, грунты и лаки. Остаток в литрах; цвет и блеск — отдельные карточки.",
        )
    else:
        group.has_grade = False
        group.has_sheet_size = False
        group.save(update_fields=["has_grade", "has_sheet_size"])

    for i, type_name in enumerate(COATING_TYPES):
        MaterialGroupType.objects.get_or_create(
            group=group,
            name=type_name,
            defaults={"sort_order": i},
        )

    for name in STAIN_NAMES:
        Material.objects.get_or_create(
            name=name,
            defaults={
                "group": group,
                "material_type": "морилка водная",
                "unit": "л",
            },
        )


def unseed_coatings(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    Material.objects.filter(name__in=STAIN_NAMES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0103_materialgroup_packaging_sheet_flag"),
    ]

    operations = [
        migrations.RunPython(seed_coatings, unseed_coatings),
    ]
