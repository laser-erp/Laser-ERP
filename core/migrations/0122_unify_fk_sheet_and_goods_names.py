from decimal import Decimal

from django.db import migrations

GROUP_SANDED = "Фанера ФК шлифованный"
GROUP_PRIMED = "Фанера ФК грунтованный"

# Сырой лист: Фанера ФК {Д}×{Ш} сорт 2/2 {Т} мм
# ГП: то же + шлифованный / грунтованный
MATERIAL_ROWS = (
    {
        "new": "Фанера ФК 900×600 сорт 2/2 3 мм",
        "old": ("Фанера ФК 900*600 сорт 2/2 3мм", "Фанера ФК 900×600 сорт 2/2 3 мм"),
        "length": Decimal("900"),
        "width": Decimal("600"),
        "thickness": Decimal("3"),
    },
    {
        "new": "Фанера ФК 900×600 сорт 2/2 4 мм",
        "old": ("Фанера ФК 900*600 сорт 2/2 4мм", "Фанера ФК 900×600 сорт 2/2 4 мм"),
        "length": Decimal("900"),
        "width": Decimal("600"),
        "thickness": Decimal("4"),
    },
    {
        "new": "Фанера ФК 900×600 сорт 2/2 6 мм",
        "old": (
            "Фанера ФК 900*600 сорт 2/2 6 мм",
            "Фанера ФК 900*600 сорт 2/2",
            "Фанера ФК 900×600 сорт 2/2 6 мм",
        ),
        "length": Decimal("900"),
        "width": Decimal("600"),
        "thickness": Decimal("6"),
    },
    {
        "new": "Фанера ФК 621×621 сорт 2/2 3 мм",
        "old": ("Фанера ФК 621*621 сорт 2/2 3мм", "Фанера ФК 621×621 сорт 2/2 3 мм"),
        "length": Decimal("621"),
        "width": Decimal("621"),
        "thickness": Decimal("3"),
    },
    {
        "new": "Фанера ФК 621×621 сорт 2/2 4 мм",
        "old": ("Фанера ФК 621*621 сорт 2/2 4мм", "Фанера ФК 621×621 сорт 2/2 4 мм"),
        "length": Decimal("621"),
        "width": Decimal("621"),
        "thickness": Decimal("4"),
    },
    {
        "new": "Фанера ФК 621×621 сорт 2/2 6 мм",
        "old": (
            "Фанера ФК 621*621 сорт 2/2 6мм",
            "Фанера ФК 621*621 сорт 2/2",
            "Фанера ФК 621×621 сорт 2/2 6 мм",
        ),
        "length": Decimal("621"),
        "width": Decimal("621"),
        "thickness": Decimal("6"),
    },
    {
        "new": "Фанера ФК 317×900 сорт 2/2 3 мм",
        "old": ("Фанера ФК 317*900 сорт 2/2 3мм", "Фанера ФК 317×900 сорт 2/2 3 мм"),
        "length": Decimal("317"),
        "width": Decimal("900"),
        "thickness": Decimal("3"),
    },
    {
        "new": "Фанера ФК 317×900 сорт 2/2 4 мм",
        "old": ("Фанера ФК 317*900 сорт 2/2 4мм", "Фанера ФК 317×900 сорт 2/2 4 мм"),
        "length": Decimal("317"),
        "width": Decimal("900"),
        "thickness": Decimal("4"),
    },
    {
        "new": "Фанера ФК 317×900 сорт 2/2 6 мм",
        "old": (
            "Фанера ФК 317*900 сорт 2/2 6мм",
            "Фанера ФК 317*900 сорт 2/2",
            "Фанера ФК 317×900 сорт 2/2 6 мм",
        ),
        "length": Decimal("317"),
        "width": Decimal("900"),
        "thickness": Decimal("6"),
    },
)

PRODUCT_RENAMES = (
    (
        "Фанера ФК шлифованный 900×600 6 мм",
        "Фанера ФК 900×600 сорт 2/2 6 мм шлифованный",
        GROUP_SANDED,
        Decimal("900"),
        Decimal("600"),
        Decimal("6"),
    ),
    (
        "Фанера ФК грунтованный 900×600 6 мм",
        "Фанера ФК 900×600 сорт 2/2 6 мм грунтованный",
        GROUP_PRIMED,
        Decimal("900"),
        Decimal("600"),
        Decimal("6"),
    ),
)

NEW_GOODS = (
    {
        "name": "Фанера ФК 317×900 сорт 2/2 4 мм шлифованный",
        "group": GROUP_SANDED,
        "length": Decimal("317"),
        "width": Decimal("900"),
        "thickness": Decimal("4"),
    },
    {
        "name": "Фанера ФК 317×900 сорт 2/2 4 мм грунтованный",
        "group": GROUP_PRIMED,
        "length": Decimal("317"),
        "width": Decimal("900"),
        "thickness": Decimal("4"),
    },
)


def _find_material(Material, names):
    for name in names:
        obj = Material.objects.filter(name=name).first()
        if obj:
            return obj
    return None


def unify_fk_sheet_and_goods_names(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    Product = apps.get_model("core", "Product")
    ProductGroup = apps.get_model("core", "ProductGroup")

    claimed = set()
    for row in MATERIAL_ROWS:
        material = _find_material(Material, row["old"])
        if material is None or material.pk in claimed:
            continue
        claimed.add(material.pk)
        Material.objects.filter(pk=material.pk).update(
            name=row["new"],
            sheet_length_mm=row["length"],
            sheet_width_mm=row["width"],
            thickness_mm=row["thickness"],
            grade="2/2",
        )

    groups = {}
    for group_name in (GROUP_SANDED, GROUP_PRIMED):
        group = ProductGroup.objects.filter(name=group_name).first()
        if group is None:
            group = ProductGroup.objects.create(name=group_name, description="")
        groups[group_name] = group

    for old_name, new_name, group_name, length, width, thickness in PRODUCT_RENAMES:
        product = Product.objects.filter(name__in=(old_name, new_name)).first()
        if product is None:
            continue
        Product.objects.filter(pk=product.pk).update(
            name=new_name,
            product_group_id=groups[group_name].pk,
            product_kind="goods",
            unit="шт",
            sheet_length_mm=length,
            sheet_width_mm=width,
            sheet_thickness_mm=thickness,
        )

    for row in NEW_GOODS:
        if Product.objects.filter(name=row["name"]).exists():
            Product.objects.filter(name=row["name"]).update(
                product_group_id=groups[row["group"]].pk,
                product_kind="goods",
                unit="шт",
                sheet_length_mm=row["length"],
                sheet_width_mm=row["width"],
                sheet_thickness_mm=row["thickness"],
            )
            continue
        Product.objects.create(
            name=row["name"],
            product_kind="goods",
            product_group_id=groups[row["group"]].pk,
            unit="шт",
            min_stock=0,
            sheet_length_mm=row["length"],
            sheet_width_mm=row["width"],
            sheet_thickness_mm=row["thickness"],
        )
        created = Product.objects.filter(name=row["name"]).order_by("pk").last()
        if created is not None and not (created.article or "").strip():
            Product.objects.filter(pk=created.pk).update(article=f"ART-{created.pk:06d}")


def noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0121_merge_duplicate_sanded_sheet_group"),
    ]

    operations = [
        migrations.RunPython(unify_fk_sheet_and_goods_names, noop_reverse),
    ]
