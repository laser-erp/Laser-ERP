from django.db import migrations


def forwards(apps, schema_editor):
    Product = apps.get_model("core", "Product")
    Material = apps.get_model("core", "Material")
    for p in Product.objects.filter(product_kind="material"):
        name = (p.name or "").strip()
        if not name:
            continue
        name = name[:255]
        unit = ((p.unit or "").strip() or "шт")[:50]
        m = Material.objects.filter(name__iexact=name).order_by("pk").first()
        if m:
            Material.objects.filter(pk=m.pk).update(
                group_id=p.material_group_id,
                unit=unit or m.unit,
            )
        else:
            Material.objects.create(
                name=name,
                group_id=p.material_group_id,
                unit=unit,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0073_product_material_group"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
