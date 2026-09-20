# Generated manually — один лист сырья на техкарте таблички

from django.db import migrations


def fix_tablichka_duplicate_sheet_rows(apps, schema_editor):
    TechCard = apps.get_model("core", "TechCard")
    TechCardItem = apps.get_model("core", "TechCardItem")
    Material = apps.get_model("core", "Material")

    tc = TechCard.objects.filter(name="Табличка Баня из фанеры 3 мм").first()
    if tc is None:
        return
    sheet = Material.objects.filter(name="Фанера ФК 317×900 сорт 2/2 3 мм").first()
    if sheet is None:
        return
    items = list(
        TechCardItem.objects.filter(tech_card=tc, material_id=sheet.pk).order_by("pk")
    )
    if not items:
        return
    first = items[0]
    first.item_kind = "raw"
    first.save(update_fields=["item_kind"])
    for row in items[1:]:
        row.delete()

    if tc.product_id:
        from core.models import TechCard as LiveTechCard

        live = LiveTechCard.objects.filter(pk=tc.pk).first()
        if live:
            live.sync_material_norms_to_product()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0132_production_request_order_mode_quote"),
    ]

    operations = [
        migrations.RunPython(fix_tablichka_duplicate_sheet_rows, noop),
    ]
