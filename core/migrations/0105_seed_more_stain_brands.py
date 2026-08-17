from django.db import migrations

# Древесные цвета с полок Лемана ПРО / Максидом. Декор (лайм, малахит) не заводим.
NEW_STAINS = (
    ("Master Good", ("Махагон", "Красное дерево")),
    ("Luxens", ("Дуб", "Орех", "Лиственница", "Сосна", "Махагон")),
    ("Вершина", ("Дуб", "Орех", "Сосна", "Махагон", "Мокко", "Эбеновое дерево")),
    ("Tury", ("Дуб", "Орех", "Лиственница", "Сосна", "Палисандр")),
)


def _names():
    names = []
    for brand, colors in NEW_STAINS:
        for color in colors:
            names.append(f"Морилка водная {brand} «{color}»")
    return names


def seed_more_stains(apps, schema_editor):
    MaterialGroup = apps.get_model("core", "MaterialGroup")
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

    for name in _names():
        Material.objects.get_or_create(
            name=name,
            defaults={
                "group": group,
                "material_type": "морилка водная",
                "unit": "л",
            },
        )


def unseed_more_stains(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    Material.objects.filter(name__in=_names()).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0104_seed_coatings_stains"),
    ]

    operations = [
        migrations.RunPython(seed_more_stains, unseed_more_stains),
    ]
