from decimal import Decimal

from django.db import migrations

GROUP_SANDED = "Фанера ФК шлифованный"
GROUP_PRIMED = "Фанера ФК грунтованный"

SHEETS_3MM = (
    {
        "new": "Фанера ФК 900×600 сорт 2/2 3 мм",
        "old": ("Фанера ФК 900*600 сорт 2/2 3мм", "Фанера ФК 900×600 сорт 2/2 3 мм"),
        "length": Decimal("900"),
        "width": Decimal("600"),
    },
    {
        "new": "Фанера ФК 317×900 сорт 2/2 3 мм",
        "old": ("Фанера ФК 317*900 сорт 2/2 3мм", "Фанера ФК 317×900 сорт 2/2 3 мм"),
        "length": Decimal("317"),
        "width": Decimal("900"),
    },
)

NEW_GOODS = (
    {
        "name": "Фанера ФК 900×600 сорт 2/2 3 мм шлифованный",
        "group": GROUP_SANDED,
        "length": Decimal("900"),
        "width": Decimal("600"),
    },
    {
        "name": "Фанера ФК 900×600 сорт 2/2 3 мм грунтованный",
        "group": GROUP_PRIMED,
        "length": Decimal("900"),
        "width": Decimal("600"),
    },
    {
        "name": "Фанера ФК 317×900 сорт 2/2 3 мм шлифованный",
        "group": GROUP_SANDED,
        "length": Decimal("317"),
        "width": Decimal("900"),
    },
    {
        "name": "Фанера ФК 317×900 сорт 2/2 3 мм грунтованный",
        "group": GROUP_PRIMED,
        "length": Decimal("317"),
        "width": Decimal("900"),
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


def _ensure_group(ProductGroup, name):
    group = ProductGroup.objects.filter(name=name).first()
    if group is None:
        group = ProductGroup.objects.create(name=name, description="")
    return group


def seed_3mm_goods(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    MaterialGroupType = apps.get_model("core", "MaterialGroupType")
    Product = apps.get_model("core", "Product")
    ProductGroup = apps.get_model("core", "ProductGroup")
    sheet_group = _new_sheet_group(apps)
    MaterialGroupType.objects.get_or_create(
        group=sheet_group,
        name="Фанера ФК",
        defaults={"sort_order": 0},
    )
    for row in SHEETS_3MM:
        material = None
        for name in row["old"]:
            material = Material.objects.filter(name=name).first()
            if material is not None:
                break
        fields = {
            "name": row["new"],
            "group": sheet_group,
            "material_type": "Фанера ФК",
            "unit": "лист",
            "sheet_length_mm": row["length"],
            "sheet_width_mm": row["width"],
            "thickness_mm": Decimal("3"),
            "grade": "2/2",
        }
        if material is None:
            Material.objects.create(**fields)
        else:
            Material.objects.filter(pk=material.pk).update(
                name=row["new"],
                sheet_length_mm=row["length"],
                sheet_width_mm=row["width"],
                thickness_mm=Decimal("3"),
                grade="2/2",
            )

    groups = {
        GROUP_SANDED: _ensure_group(ProductGroup, GROUP_SANDED),
        GROUP_PRIMED: _ensure_group(ProductGroup, GROUP_PRIMED),
    }
    for row in NEW_GOODS:
        fields = {
            "product_group_id": groups[row["group"]].pk,
            "product_kind": "goods",
            "unit": "шт",
            "sheet_length_mm": row["length"],
            "sheet_width_mm": row["width"],
            "sheet_thickness_mm": Decimal("3"),
        }
        existing = Product.objects.filter(name=row["name"]).first()
        if existing is not None:
            Product.objects.filter(pk=existing.pk).update(**fields)
            continue
        created = Product.objects.create(name=row["name"], min_stock=0, **fields)
        if not (created.article or "").strip():
            Product.objects.filter(pk=created.pk).update(article=f"ART-{created.pk:06d}")


def noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0124_ensure_fk_621x621_3mm_sheet"),
    ]

    operations = [
        migrations.RunPython(seed_3mm_goods, noop_reverse),
    ]
