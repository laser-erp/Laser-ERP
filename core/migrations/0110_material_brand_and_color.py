import re

import django.db.models.deletion
from django.db import migrations, models


COATING_BRANDS = (
    "Master Good",
    "Luxens",
    "Вершина",
    "Tury",
    "Акватекс",
)

COATING_COLORS = (
    "Дуб",
    "Орех",
    "Лиственница",
    "Сосна",
    "Мокко",
    "Эбеновое дерево",
    "Махагон",
    "Красное дерево",
    "Палисандр",
)

STAIN_RE = re.compile(r"^Морилка водная (.+) «(.+)»$")
VARNISH_RE = re.compile(r"^Лак паркетный (.+) «(.+)»$")


def seed_brand_color(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    MaterialGroup = apps.get_model("core", "MaterialGroup")
    MaterialGroupBrand = apps.get_model("core", "MaterialGroupBrand")
    MaterialGroupColor = apps.get_model("core", "MaterialGroupColor")

    for group in MaterialGroup.objects.all():
        name_n = (group.name or "").casefold().replace("ё", "е")
        if "покрыт" not in name_n:
            continue
        group.has_brand = True
        group.has_color = True
        group.save(update_fields=["has_brand", "has_color"])
        for i, brand in enumerate(COATING_BRANDS):
            MaterialGroupBrand.objects.get_or_create(
                group=group,
                name=brand,
                defaults={"sort_order": i},
            )
        for i, color in enumerate(COATING_COLORS):
            MaterialGroupColor.objects.get_or_create(
                group=group,
                name=color,
                defaults={"sort_order": i},
            )
        for material in Material.objects.filter(group=group):
            name = (material.name or "").strip()
            stain = STAIN_RE.match(name)
            varnish = VARNISH_RE.match(name)
            brand = ""
            color = ""
            if stain:
                brand = stain.group(1).strip()[:100]
                color = stain.group(2).strip()[:100]
            elif varnish:
                brand = varnish.group(1).strip()[:100]
            if not brand and not color:
                continue
            material.brand = brand
            material.color = color
            material.save(update_fields=["brand", "color"])
            if brand:
                MaterialGroupBrand.objects.get_or_create(
                    group=group,
                    name=brand,
                    defaults={"sort_order": 50},
                )
            if color:
                MaterialGroupColor.objects.get_or_create(
                    group=group,
                    name=color,
                    defaults={"sort_order": 50},
                )


def unseed_brand_color(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    MaterialGroup = apps.get_model("core", "MaterialGroup")
    MaterialGroupBrand = apps.get_model("core", "MaterialGroupBrand")
    MaterialGroupColor = apps.get_model("core", "MaterialGroupColor")
    MaterialGroupBrand.objects.all().delete()
    MaterialGroupColor.objects.all().delete()
    MaterialGroup.objects.update(has_brand=False, has_color=False)
    Material.objects.update(brand="", color="")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0109_rename_akvateks_parquet_varnish"),
    ]

    operations = [
        migrations.AddField(
            model_name="materialgroup",
            name="has_brand",
            field=models.BooleanField(
                default=False,
                help_text="Включите для покрытий: в карточке появится список брендов (Master Good, Tury…).",
                verbose_name="Указывать бренд",
            ),
        ),
        migrations.AddField(
            model_name="materialgroup",
            name="has_color",
            field=models.BooleanField(
                default=False,
                help_text="Включите для морилки: в карточке появится список цветов. У лака поле скрыто.",
                verbose_name="Указывать цвет",
            ),
        ),
        migrations.AddField(
            model_name="material",
            name="brand",
            field=models.CharField(
                blank=True,
                help_text="Марка с полки. Для морилки вместе с цветом собирает наименование карточки.",
                max_length=100,
                verbose_name="Бренд",
            ),
        ),
        migrations.AddField(
            model_name="material",
            name="color",
            field=models.CharField(
                blank=True,
                help_text="Цвет морилки (дуб, орех…). У бесцветного лака не заполняется.",
                max_length=100,
                verbose_name="Цвет",
            ),
        ),
        migrations.CreateModel(
            name="MaterialGroupBrand",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, verbose_name="Бренд")),
                ("sort_order", models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="brand_choices",
                        to="core.materialgroup",
                        verbose_name="Группа",
                    ),
                ),
            ],
            options={
                "verbose_name": "Бренд в группе",
                "verbose_name_plural": "Бренды в группе",
                "ordering": ["sort_order", "name"],
                "constraints": [
                    models.UniqueConstraint(fields=("group", "name"), name="uniq_material_group_brand_name")
                ],
            },
        ),
        migrations.CreateModel(
            name="MaterialGroupColor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, verbose_name="Цвет")),
                ("sort_order", models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="color_choices",
                        to="core.materialgroup",
                        verbose_name="Группа",
                    ),
                ),
            ],
            options={
                "verbose_name": "Цвет в группе",
                "verbose_name_plural": "Цвета в группе",
                "ordering": ["sort_order", "name"],
                "constraints": [
                    models.UniqueConstraint(fields=("group", "name"), name="uniq_material_group_color_name")
                ],
            },
        ),
        migrations.RunPython(seed_brand_color, unseed_brand_color),
    ]
