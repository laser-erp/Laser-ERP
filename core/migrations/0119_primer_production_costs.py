from decimal import Decimal
from importlib import import_module

from django.db import migrations

_m117 = import_module("core.migrations.0117_seed_fk_900x600x6_tech_cards")


def _copy_people(src, dest):
    if src is None or dest is None or src.pk == dest.pk:
        return
    fields = []
    if src.master_id and dest.master_id != src.master_id:
        dest.master_id = src.master_id
        fields.append("master")
    if fields:
        dest.save(update_fields=fields)
    src_ids = list(src.executors.values_list("pk", flat=True))
    if src_ids:
        dest.executors.add(*src_ids)


def _upsert_labor(TechCardLaborLine, card, stage, hours, minutes, overhead):
    line = TechCardLaborLine.objects.filter(tech_card=card, production_stage=stage).first()
    if line is None:
        TechCardLaborLine.objects.create(
            tech_card=card,
            production_stage=stage,
            norm_hours=hours,
            employee_minutes=minutes,
            overhead_per_unit=overhead,
        )
        return
    line.norm_hours = hours
    line.employee_minutes = minutes
    line.overhead_per_unit = overhead
    line.save(update_fields=["norm_hours", "employee_minutes", "overhead_per_unit"])


def fill_production_costs(apps, schema_editor):
    ProductionStage = apps.get_model("core", "ProductionStage")
    TechCard = apps.get_model("core", "TechCard")
    TechCardLaborLine = apps.get_model("core", "TechCardLaborLine")

    side1 = ProductionStage.objects.filter(name=_m117.STAGE_SIDE1).first()
    side2 = ProductionStage.objects.filter(name=_m117.STAGE_SIDE2).first()
    coat_s1 = ProductionStage.objects.filter(name=_m117.STAGE_COAT_S1).first()
    coat_s2 = ProductionStage.objects.filter(name=_m117.STAGE_COAT_S2).first()
    dry_s1 = ProductionStage.objects.filter(name=_m117.STAGE_DRY_S1).first()
    dry_s2 = ProductionStage.objects.filter(name=_m117.STAGE_DRY_S2).first()
    people_src = coat_s1 or side1
    _copy_people(side1, side2)
    _copy_people(people_src, coat_s2)
    _copy_people(people_src, dry_s1)
    _copy_people(people_src, dry_s2)

    card = TechCard.objects.filter(name=_m117.CARD_B_NAME).first()
    if card is None or dry_s1 is None or dry_s2 is None:
        return
    _upsert_labor(
        TechCardLaborLine,
        card,
        dry_s1,
        _m117.DRY_HOURS,
        _m117.DRY_EMP_MIN,
        _m117.DRY_OVERHEAD_PER_SIDE,
    )
    _upsert_labor(
        TechCardLaborLine,
        card,
        dry_s2,
        _m117.DRY_HOURS,
        _m117.DRY_EMP_MIN,
        _m117.DRY_OVERHEAD_PER_SIDE,
    )


def noop(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0118_primer_drying_per_side"),
    ]

    operations = [
        migrations.RunPython(fill_production_costs, noop),
    ]
