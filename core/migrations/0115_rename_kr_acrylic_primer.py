from django.db import migrations

OLD_NAME = "Грунт акриловый КР «глубокого проникновения»"
NEW_NAME = "Грунт акриловый «глубокого проникновения»"


def rename_forward(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    Material.objects.filter(name=OLD_NAME).update(name=NEW_NAME, brand="")
    Material.objects.filter(name=NEW_NAME).exclude(brand="").update(brand="")


def rename_backward(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    Material.objects.filter(name=NEW_NAME).update(name=OLD_NAME, brand="КР")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0114_seed_kr_acrylic_primer"),
    ]

    operations = [
        migrations.RunPython(rename_forward, rename_backward),
    ]
