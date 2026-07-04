# Дополнительные техпроцессы шлифования по аналогии с P100 / P100→P120.

from django.db import migrations


STAGE_SIDE1 = "Шлифование материала сторона 1"
STAGE_SIDE2 = "Шлифование материала сторона 2"
STAGE_AFTER_CUT = "Шлифование после резки"
STAGE_INTER1 = "Промежуточное шлифование после просушки 1 -го слоя покрытия"
STAGE_INTER2 = "Промежуточное шлифование после просушки 2 -го слоя покрытия"

# Имена техпроцессов, созданных этой миграцией (для отката).
CREATED_TECH_PROCESS_NAMES = [
    "Шлифование абразивом P120 с одной стороны",
    "Шлифование абразивом P120 с двух сторон",
    "Шлифование абразивом P180 с одной стороны",
    "Шлифование абразивом P180 с двух сторон",
    "Шлифование абразивом P120->P180 с одной стороны",
    "Шлифование абразивом P120->P180 с двух сторон",
    "Шлифование абразивом P180->P240 с одной стороны",
    "Шлифование абразивом P180->P240 с двух сторон",
    "Шлифование абразивом P240 с одной стороны",
    "Шлифование абразивом P240 с двух сторон",
    "Шлифование абразивом P320 с одной стороны",
    "Шлифование абразивом P320 с двух сторон",
    "Шлифование абразивом P240->P320 с одной стороны",
    "Шлифование абразивом P240->P320 с двух сторон",
    "Шлифование после раскроя абразивом P120",
    "Межслойное шлифование после 1-го слоя покрытия абразивом P320",
    "Межслойное шлифование после 2-го слоя покрытия абразивом P400",
]


def forwards(apps, schema_editor):
    TechProcess = apps.get_model("core", "TechProcess")
    TechProcessStage = apps.get_model("core", "TechProcessStage")
    ProductionStage = apps.get_model("core", "ProductionStage")

    def stage_by_name(name: str):
        return ProductionStage.objects.filter(name=name).first()

    def ensure_tech_process(name: str, description: str, stage_names: list[str]) -> None:
        if TechProcess.objects.filter(name=name).exists():
            return
        pks = []
        for sn in stage_names:
            st = stage_by_name(sn)
            if st is None:
                return
            pks.append(st.pk)
        tp = TechProcess.objects.create(name=name, description=description)
        for order, pk in enumerate(pks, start=1):
            TechProcessStage.objects.create(
                tech_process=tp,
                production_stage_id=pk,
                order=order,
            )

    # Одна / две стороны — как у P100 и P100→P120
    singles = [
        ("P120", "Шлифуем абразивом P120 до однородности материала."),
        ("P180", "Шлифуем абразивом P180 до однородности материала (подготовка под грунт)."),
        ("P240", "Шлифуем абразивом P240 до однородности материала (после грунта / межслойная подготовка)."),
        ("P320", "Шлифуем абразивом P320 до однородности материала (межслойное шлифование покрытия)."),
    ]
    for grit, desc_one in singles:
        ensure_tech_process(
            f"Шлифование абразивом {grit} с одной стороны",
            desc_one + " Сторона 1.",
            [STAGE_SIDE1],
        )
        ensure_tech_process(
            f"Шлифование абразивом {grit} с двух сторон",
            f"Шлифуем материал абразивом {grit} с двух сторон.",
            [STAGE_SIDE1, STAGE_SIDE2],
        )

    combos = [
        ("P120->P180", "Шлифуем абразивом P120->P180 до однородности материала."),
        ("P180->P240", "Шлифуем абразивом P180->P240 до однородности материала."),
        ("P240->P320", "Шлифуем абразивом P240->P320 до однородности материала."),
    ]
    for grit, desc_base in combos:
        ensure_tech_process(
            f"Шлифование абразивом {grit} с одной стороны",
            desc_base + " Сторона 1.",
            [STAGE_SIDE1],
        )
        ensure_tech_process(
            f"Шлифование абразивом {grit} с двух сторон",
            f"Шлифуем материал абразивом {grit} с двух сторон.",
            [STAGE_SIDE1, STAGE_SIDE2],
        )

    ensure_tech_process(
        "Шлифование после раскроя абразивом P120",
        "После раскроя: P120 на кромке/следах реза, затем однородность стороны 1 и 2.",
        [STAGE_AFTER_CUT, STAGE_SIDE1, STAGE_SIDE2],
    )
    ensure_tech_process(
        "Межслойное шлифование после 1-го слоя покрытия абразивом P320",
        "Промежуточное шлифование после просушки 1-го слоя покрытия, абразив P320.",
        [STAGE_INTER1],
    )
    ensure_tech_process(
        "Межслойное шлифование после 2-го слоя покрытия абразивом P400",
        "Промежуточное шлифование после просушки 2-го слоя покрытия, абразив P400.",
        [STAGE_INTER2],
    )


def backwards(apps, schema_editor):
    TechProcess = apps.get_model("core", "TechProcess")
    TechProcess.objects.filter(name__in=CREATED_TECH_PROCESS_NAMES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0064_stage_cut_rate_and_techcard_cut_length"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
