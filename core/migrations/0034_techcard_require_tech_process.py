# Generated manually: обязательный техпроцесс у техкарты

import django.db.models.deletion
from django.db import migrations, models


def assign_default_tech_process(apps, schema_editor):
    TechCard = apps.get_model("core", "TechCard")
    TechProcess = apps.get_model("core", "TechProcess")
    orphaned = TechCard.objects.filter(tech_process__isnull=True)
    if not orphaned.exists():
        return
    tp = TechProcess.objects.order_by("pk").first()
    if tp is None:
        tp = TechProcess.objects.create(
            name="Техпроцесс по умолчанию",
            description="Создано миграцией: к техкартам без техпроцесса. При необходимости переименуйте или замените в карточках.",
        )
    orphaned.update(tech_process_id=tp.pk)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0033_techcard_clear_tech_process_help"),
    ]

    operations = [
        migrations.RunPython(assign_default_tech_process, noop_reverse),
        migrations.AlterField(
            model_name="techcard",
            name="tech_process",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="tech_cards",
                to="core.techprocess",
                verbose_name="Техпроцесс",
            ),
        ),
    ]
