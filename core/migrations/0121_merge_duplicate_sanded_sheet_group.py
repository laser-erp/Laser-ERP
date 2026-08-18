from django.db import migrations


SANDED_GROUP_NAME = "Лист Шлифованный"


def merge_duplicate_sanded_groups(apps, schema_editor):
    MaterialGroup = apps.get_model("core", "MaterialGroup")
    Material = apps.get_model("core", "Material")
    Product = apps.get_model("core", "Product")
    groups = list(MaterialGroup.objects.filter(name=SANDED_GROUP_NAME).order_by("id"))
    if len(groups) < 2:
        return
    used = []
    for group in groups:
        has_materials = Material.objects.filter(group_id=group.id).exists()
        has_products = Product.objects.filter(material_group_id=group.id).exists()
        if has_materials or has_products:
            used.append(group)
    keeper = used[0] if used else groups[0]
    for group in groups:
        if group.id == keeper.id:
            continue
        Material.objects.filter(group_id=group.id).update(group_id=keeper.id)
        Product.objects.filter(material_group_id=group.id).update(material_group_id=keeper.id)
        group.delete()


def noop(apps, schema_editor):
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0120_material_purchase_price"),
    ]

    operations = [
        migrations.RunPython(merge_duplicate_sanded_groups, noop),
    ]
