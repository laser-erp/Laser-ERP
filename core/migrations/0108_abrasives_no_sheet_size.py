from django.db import migrations


def disable_sheet_size_for_abrasives(apps, schema_editor):
    MaterialGroup = apps.get_model("core", "MaterialGroup")
    Material = apps.get_model("core", "Material")

    group_ids = []
    for group in MaterialGroup.objects.all():
        name_n = (group.name or "").casefold().replace("ё", "е")
        if "абразив" not in name_n:
            continue
        group.has_grade = False
        group.has_sheet_size = False
        group.save(update_fields=["has_grade", "has_sheet_size"])
        group_ids.append(group.pk)

    if group_ids:
        Material.objects.filter(group_id__in=group_ids).update(
            sheet_length_mm=None,
            sheet_width_mm=None,
            thickness_mm=None,
        )


def enable_sheet_size_for_abrasives(apps, schema_editor):
    MaterialGroup = apps.get_model("core", "MaterialGroup")
    for group in MaterialGroup.objects.all():
        name_n = (group.name or "").casefold().replace("ё", "е")
        if "абразив" in name_n:
            group.has_sheet_size = True
            group.save(update_fields=["has_sheet_size"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0107_seed_flexione_discs"),
    ]

    operations = [
        migrations.RunPython(disable_sheet_size_for_abrasives, enable_sheet_size_for_abrasives),
    ]
