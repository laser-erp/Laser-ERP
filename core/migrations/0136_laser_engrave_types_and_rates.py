# Типы гравировки на строке техкарты; ₽/м² на этапе; ориентиры на «Лазерной гравировке»

from decimal import Decimal

from django.db import migrations, models


def seed_engrave_stage_rates(apps, schema_editor):
    ProductionStage = apps.get_model("core", "ProductionStage")
    for pk, name in ProductionStage.objects.values_list("pk", "name"):
        n = (name or "").lower().replace("ё", "е")
        if "гравир" not in n:
            continue
        ProductionStage.objects.filter(pk=pk).update(
            cut_rate_per_meter=Decimal("20.00"),
            engrave_fill_rate_per_sq_m=Decimal("2500.00"),
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0135_laser_cut_items_no_material"),
    ]

    operations = [
        migrations.AddField(
            model_name="productionstage",
            name="engrave_fill_rate_per_sq_m",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Только этап «Лазерная гравировка»: заливка/растр. В техкарте — тип «Заливка» и площадь м² на 1 изделие.",
                max_digits=12,
                null=True,
                verbose_name="Стоимость сплошной гравировки, ₽/м²",
            ),
        ),
        migrations.AddField(
            model_name="techcarditem",
            name="engrave_area_m2",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                help_text="Тип «Заливка»: площадь закрашиваемой зоны на одно изделие.",
                max_digits=12,
                null=True,
                verbose_name="Площадь гравировки на 1 изд., м²",
            ),
        ),
        migrations.AddField(
            model_name="techcarditem",
            name="engrave_kind",
            field=models.CharField(
                blank=True,
                choices=[
                    ("contour", "Контурная (вектор)"),
                    ("fill", "Заливка (растр)"),
                ],
                default="",
                help_text="Только для этапа «Лазерная гравировка».",
                max_length=20,
                verbose_name="Тип гравировки",
            ),
        ),
        migrations.RunPython(seed_engrave_stage_rates, noop),
    ]
