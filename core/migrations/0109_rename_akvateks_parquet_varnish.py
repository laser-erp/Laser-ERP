from django.db import migrations


RENAME = (
    ("Лак акриловый Акватекс «матовый»", "Лак паркетный Акватекс «матовый»"),
    ("Лак акриловый Акватекс «полуматовый»", "Лак паркетный Акватекс «полуматовый»"),
    ("Лак акриловый Акватекс «глянцевый»", "Лак паркетный Акватекс «глянцевый»"),
)


def rename_forward(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    for old, new in RENAME:
        Material.objects.filter(name=old).update(name=new)


def rename_backward(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    for old, new in RENAME:
        Material.objects.filter(name=new).update(name=old)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0108_abrasives_no_sheet_size"),
    ]

    operations = [
        migrations.RunPython(rename_forward, rename_backward),
    ]
