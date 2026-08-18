from decimal import Decimal

from django.db import migrations

GROUP_SANDED = "Фанера ФК шлифованный"
GROUP_PRIMED = "Фанера ФК грунтованный"

NEW_GOODS = tuple(
    {
        "name": f"Фанера ФК 621×621 сорт 2/2 {thick} мм {adj}",
        "group": group,
        "length": Decimal("621"),
        "width": Decimal("621"),
        "thickness": Decimal(str(thick)),
    }
    for thick in (3, 4, 6)
    for adj, group in (("шлифованный", GROUP_SANDED), ("грунтованный", GROUP_PRIMED))
)


def _ensure_group(ProductGroup, name):
    group = ProductGroup.objects.filter(name=name).first()
    if group is None:
        group = ProductGroup.objects.create(name=name, description="")
    return group


def seed_621_goods(apps, schema_editor):
    Product = apps.get_model("core", "Product")
    ProductGroup = apps.get_model("core", "ProductGroup")
    groups = {
        GROUP_SANDED: _ensure_group(ProductGroup, GROUP_SANDED),
        GROUP_PRIMED: _ensure_group(ProductGroup, GROUP_PRIMED),
    }
    for row in NEW_GOODS:
        existing = Product.objects.filter(name=row["name"]).first()
        fields = {
            "product_group_id": groups[row["group"]].pk,
            "product_kind": "goods",
            "unit": "шт",
            "sheet_length_mm": row["length"],
            "sheet_width_mm": row["width"],
            "sheet_thickness_mm": row["thickness"],
        }
        if existing is not None:
            Product.objects.filter(pk=existing.pk).update(**fields)
            continue
        created = Product.objects.create(
            name=row["name"],
            min_stock=0,
            **fields,
        )
        if not (created.article or "").strip():
            Product.objects.filter(pk=created.pk).update(article=f"ART-{created.pk:06d}")


def noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0122_unify_fk_sheet_and_goods_names"),
    ]

    operations = [
        migrations.RunPython(seed_621_goods, noop_reverse),
    ]
