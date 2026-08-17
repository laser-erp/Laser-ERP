from decimal import Decimal
from importlib import import_module

from django.db import migrations

_m117 = import_module("core.migrations.0117_seed_fk_900x600x6_tech_cards")


def _upsert_labor(TechCardLaborLine, card, stage, hours, minutes):
    line = TechCardLaborLine.objects.filter(tech_card=card, production_stage=stage).first()
    if line is None:
        TechCardLaborLine.objects.create(
            tech_card=card,
            production_stage=stage,
            norm_hours=hours,
            employee_minutes=minutes,
        )
        return
    line.norm_hours = hours
    line.employee_minutes = minutes
    line.save(update_fields=["norm_hours", "employee_minutes"])


def split_primer_drying(apps, schema_editor):
    ProductionStage = apps.get_model("core", "ProductionStage")
    TechCard = apps.get_model("core", "TechCard")
    TechCardLaborLine = apps.get_model("core", "TechCardLaborLine")
    TechProcess = apps.get_model("core", "TechProcess")
    TechProcessStage = apps.get_model("core", "TechProcessStage")

    side1 = ProductionStage.objects.filter(name=_m117.STAGE_SIDE1).first()
    coat_s1 = ProductionStage.objects.filter(name=_m117.STAGE_COAT_S1).first()
    coat_s2 = ProductionStage.objects.filter(name=_m117.STAGE_COAT_S2).first()
    inter1 = ProductionStage.objects.filter(name=_m117.STAGE_INTER1).first()
    if not all([coat_s1, coat_s2, inter1]):
        return

    dry_s1 = _m117._ensure_stage(
        ProductionStage, _m117.STAGE_DRY_S1, template=side1, hourly_rate=Decimal("0")
    )
    dry_s2 = _m117._ensure_stage(
        ProductionStage, _m117.STAGE_DRY_S2, template=side1, hourly_rate=Decimal("0")
    )
    _m117._ensure_process(
        TechProcess,
        TechProcessStage,
        _m117.PROCESS_B_NAME,
        "Один слой грунта: сторона 1 → сушка → сторона 2 → сушка → P320. Сушка после каждой стороны отдельно.",
        [coat_s1, dry_s1, coat_s2, dry_s2, inter1],
    )

    card = TechCard.objects.filter(name=_m117.CARD_B_NAME).first()
    if card is None:
        return
    generic_dry = ProductionStage.objects.filter(name=_m117.STAGE_DRY).first()
    if generic_dry:
        TechCardLaborLine.objects.filter(
            tech_card=card, production_stage=generic_dry
        ).delete()
    _upsert_labor(TechCardLaborLine, card, coat_s1, _m117.COAT_HOURS, _m117.COAT_EMP_MIN)
    _upsert_labor(TechCardLaborLine, card, dry_s1, _m117.DRY_HOURS, _m117.DRY_EMP_MIN)
    _upsert_labor(TechCardLaborLine, card, coat_s2, _m117.COAT_HOURS, _m117.COAT_EMP_MIN)
    _upsert_labor(TechCardLaborLine, card, dry_s2, _m117.DRY_HOURS, _m117.DRY_EMP_MIN)
    _upsert_labor(TechCardLaborLine, card, inter1, _m117.INTER_HOURS, _m117.INTER_EMP_MIN)


def noop(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0117_seed_fk_900x600x6_tech_cards"),
    ]

    operations = [
        migrations.RunPython(split_primer_drying, noop),
    ]
