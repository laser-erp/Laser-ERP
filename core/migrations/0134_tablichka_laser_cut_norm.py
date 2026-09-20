# Норма метров реза без повторного списания листа

from decimal import Decimal

from django.db import migrations


def add_laser_cut_norm(apps, schema_editor):
    TechCard = apps.get_model("core", "TechCard")
    TechCardItem = apps.get_model("core", "TechCardItem")
    ProductionStage = apps.get_model("core", "ProductionStage")
    Material = apps.get_model("core", "Material")

    tc = TechCard.objects.filter(name="Табличка Баня из фанеры 3 мм").first()
    if tc is None:
        return
    stage = ProductionStage.objects.filter(name="Лазерная резка").first()
    sheet = Material.objects.filter(name="Фанера ФК 317×900 сорт 2/2 3 мм").first()
    if stage is None or sheet is None:
        return
    if TechCardItem.objects.filter(tech_card=tc, production_stage=stage).exists():
        return
    TechCardItem.objects.create(
        tech_card=tc,
        material_id=sheet.pk,
        item_kind="material",
        quantity=Decimal("0"),
        production_stage=stage,
        cut_length_meters_per_unit=Decimal("0.46"),
        note="Метры реза; лист уже в строке «Сырьё», кол-во 0",
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0133_techcard_single_raw_sheet"),
    ]

    operations = [
        migrations.RunPython(add_laser_cut_norm, noop),
    ]
