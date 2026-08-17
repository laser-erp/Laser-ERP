import re

from django.db import migrations, models


ABRASIVE_TYPES = (
    "эксцентриковый",
    "ленточный",
)

ABRASIVE_BRANDS = (
    "Flexione",
    "Abraforce",
)

ABRASIVE_GRITS = (
    "P100",
    "P120",
    "P150",
    "P180",
    "P220",
    "P240",
    "P280",
    "P320",
    "P400",
)

ABRASIVE_DIAMETERS = (
    "125",
    "150",
)

ABRASIVE_HOLES = ("8",)

DISC_RE = re.compile(
    r"^Круг шлифовальный (.+) (\d+)мм (.+) отв\. \((P\d+)\)$",
    re.IGNORECASE,
)
BRAND_CANON = {
    "flexione": "Flexione",
    "abraforce": "Abraforce",
}


def _canon_brand(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    return BRAND_CANON.get(raw.casefold(), raw)


def _ensure_choice(model, group, name, sort_order):
    label = (name or "").strip()
    if not label:
        return
    model.objects.get_or_create(
        group=group,
        name=label,
        defaults={"sort_order": sort_order},
    )


def seed_abrasive_fields(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    MaterialGroup = apps.get_model("core", "MaterialGroup")
    MaterialGroupType = apps.get_model("core", "MaterialGroupType")
    MaterialGroupBrand = apps.get_model("core", "MaterialGroupBrand")
    MaterialGroupGrit = apps.get_model("core", "MaterialGroupGrit")
    MaterialGroupDiameter = apps.get_model("core", "MaterialGroupDiameter")
    MaterialGroupHoleCount = apps.get_model("core", "MaterialGroupHoleCount")

    groups = []
    for group in MaterialGroup.objects.all():
        if "абразив" in (group.name or "").casefold().replace("ё", "е"):
            groups.append(group)
    if not groups:
        groups.append(
            MaterialGroup.objects.create(
                name="Абразивы",
                has_grade=False,
                has_sheet_size=False,
                has_brand=True,
                has_color=False,
                has_grit=True,
                has_diameter=True,
                has_hole_count=True,
            )
        )

    for group in groups:
        group.has_grade = False
        group.has_sheet_size = False
        group.has_brand = True
        group.has_grit = True
        group.has_diameter = True
        group.has_hole_count = True
        group.save(
            update_fields=[
                "has_grade",
                "has_sheet_size",
                "has_brand",
                "has_grit",
                "has_diameter",
                "has_hole_count",
            ]
        )
        for i, name in enumerate(ABRASIVE_TYPES):
            _ensure_choice(MaterialGroupType, group, name, i)
        for i, name in enumerate(ABRASIVE_BRANDS):
            _ensure_choice(MaterialGroupBrand, group, name, i)
        for i, name in enumerate(ABRASIVE_GRITS):
            _ensure_choice(MaterialGroupGrit, group, name, i)
        for i, name in enumerate(ABRASIVE_DIAMETERS):
            _ensure_choice(MaterialGroupDiameter, group, name, i)
        for i, name in enumerate(ABRASIVE_HOLES):
            _ensure_choice(MaterialGroupHoleCount, group, name, i)

        for material in Material.objects.filter(group=group):
            parsed = DISC_RE.match((material.name or "").strip())
            if not parsed:
                continue
            brand = _canon_brand(parsed.group(1))
            diameter = parsed.group(2)
            holes = parsed.group(3).strip()
            grit = parsed.group(4).upper()
            material.material_type = "эксцентриковый"
            material.brand = brand
            material.diameter_mm = diameter
            material.hole_count = holes
            material.grit = grit
            material.unit = material.unit or "шт"
            material.save(
                update_fields=[
                    "material_type",
                    "brand",
                    "diameter_mm",
                    "hole_count",
                    "grit",
                    "unit",
                ]
            )
            _ensure_choice(MaterialGroupBrand, group, brand, 50)
            _ensure_choice(MaterialGroupGrit, group, grit, 50)
            _ensure_choice(MaterialGroupDiameter, group, diameter, 50)
            _ensure_choice(MaterialGroupHoleCount, group, holes, 50)


def unseed_abrasive_fields(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    MaterialGroup = apps.get_model("core", "MaterialGroup")
    MaterialGroupType = apps.get_model("core", "MaterialGroupType")
    MaterialGroupBrand = apps.get_model("core", "MaterialGroupBrand")
    MaterialGroupGrit = apps.get_model("core", "MaterialGroupGrit")
    MaterialGroupDiameter = apps.get_model("core", "MaterialGroupDiameter")
    MaterialGroupHoleCount = apps.get_model("core", "MaterialGroupHoleCount")

    for group in MaterialGroup.objects.all():
        if "абразив" not in (group.name or "").casefold().replace("ё", "е"):
            continue
        Material.objects.filter(group=group).update(
            material_type="",
            brand="",
            grit="",
            diameter_mm="",
            hole_count="",
        )
        MaterialGroupType.objects.filter(group=group).delete()
        MaterialGroupBrand.objects.filter(group=group).delete()
        MaterialGroupGrit.objects.filter(group=group).delete()
        MaterialGroupDiameter.objects.filter(group=group).delete()
        MaterialGroupHoleCount.objects.filter(group=group).delete()
        group.has_brand = False
        group.has_grit = False
        group.has_diameter = False
        group.has_hole_count = False
        group.save(update_fields=["has_brand", "has_grit", "has_diameter", "has_hole_count"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0110_material_brand_and_color"),
    ]

    operations = [
        migrations.AddField(
            model_name="materialgroup",
            name="has_grit",
            field=models.BooleanField(
                default=False,
                help_text="Включите для абразивов: в карточке появится список зерна (P120, P150…).",
                verbose_name="Указывать зерно",
            ),
        ),
        migrations.AddField(
            model_name="materialgroup",
            name="has_diameter",
            field=models.BooleanField(
                default=False,
                help_text="Включите для кругов: в карточке появится диаметр (125, 150 мм). У ленты поле скрыто.",
                verbose_name="Указывать диаметр",
            ),
        ),
        migrations.AddField(
            model_name="materialgroup",
            name="has_hole_count",
            field=models.BooleanField(
                default=False,
                help_text="Включите для кругов: число отверстий пылеудаления. У ленты поле скрыто.",
                verbose_name="Указывать отверстия",
            ),
        ),
        migrations.AddField(
            model_name="material",
            name="grit",
            field=models.CharField(
                blank=True,
                help_text="Зерно абразива по ISO, например P120. Список задаётся у группы.",
                max_length=20,
                verbose_name="Зерно",
            ),
        ),
        migrations.AddField(
            model_name="material",
            name="diameter_mm",
            field=models.CharField(
                blank=True,
                help_text="Диаметр круга в миллиметрах (125, 150). Для ленты не заполняется.",
                max_length=20,
                verbose_name="Диаметр, мм",
            ),
        ),
        migrations.AddField(
            model_name="material",
            name="hole_count",
            field=models.CharField(
                blank=True,
                help_text="Число отверстий пылеудаления. Для ленты не заполняется.",
                max_length=20,
                verbose_name="Отверстия",
            ),
        ),
        migrations.CreateModel(
            name="MaterialGroupGrit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=20, verbose_name="Зерно")),
                ("sort_order", models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="grit_choices",
                        to="core.materialgroup",
                        verbose_name="Группа",
                    ),
                ),
            ],
            options={
                "verbose_name": "Зерно в группе",
                "verbose_name_plural": "Зерно в группе",
                "ordering": ["sort_order", "name"],
            },
        ),
        migrations.CreateModel(
            name="MaterialGroupDiameter",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=20, verbose_name="Диаметр, мм")),
                ("sort_order", models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="diameter_choices",
                        to="core.materialgroup",
                        verbose_name="Группа",
                    ),
                ),
            ],
            options={
                "verbose_name": "Диаметр в группе",
                "verbose_name_plural": "Диаметры в группе",
                "ordering": ["sort_order", "name"],
            },
        ),
        migrations.CreateModel(
            name="MaterialGroupHoleCount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=20, verbose_name="Отверстия")),
                ("sort_order", models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="hole_choices",
                        to="core.materialgroup",
                        verbose_name="Группа",
                    ),
                ),
            ],
            options={
                "verbose_name": "Отверстия в группе",
                "verbose_name_plural": "Отверстия в группе",
                "ordering": ["sort_order", "name"],
            },
        ),
        migrations.AddConstraint(
            model_name="materialgroupgrit",
            constraint=models.UniqueConstraint(fields=("group", "name"), name="uniq_material_group_grit_name"),
        ),
        migrations.AddConstraint(
            model_name="materialgroupdiameter",
            constraint=models.UniqueConstraint(fields=("group", "name"), name="uniq_material_group_diameter_name"),
        ),
        migrations.AddConstraint(
            model_name="materialgroupholecount",
            constraint=models.UniqueConstraint(fields=("group", "name"), name="uniq_material_group_hole_name"),
        ),
        migrations.RunPython(seed_abrasive_fields, unseed_abrasive_fields),
    ]
