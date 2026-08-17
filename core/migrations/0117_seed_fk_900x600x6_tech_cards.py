from decimal import Decimal

from django.db import migrations

SANDED_NAME = "Фанера ФК шлифованный 900×600 6 мм"
PRIMED_NAME = "Фанера ФК грунтованный 900×600 6 мм"
CARD_A_NAME = "Шлифование ФК 900×600×6 Ш2 P120→P180"
CARD_B_NAME = "Грунтование ФК 900×600×6 Ш2 1 слой"
GROUP_SANDED = "Фанера ФК шлифованный"
GROUP_PRIMED = "Фанера ФК грунтованный"
PROCESS_A_NAME = "Шлифование абразивом P120->P180 с двух сторон"
PROCESS_B_NAME = "Грунтование ФК Ш2 1 слой"

PLYWOOD_NAMES = (
    "Фанера ФК 900*600 сорт 2/2 6 мм",
    "Фанера ФК 900*600 сорт 2/2",
)
P120_NAME = "Круг шлифовальный FLEXIONE 125мм 8 отв. (P120)"
P180_NAME = "Круг шлифовальный FLEXIONE 125мм 8 отв. (P180)"
P320_NAME = "Круг шлифовальный FLEXIONE 125мм 8 отв. (P320)"
PRIMER_NAME = "Грунт акриловый «глубокого проникновения»"

STAGE_SIDE1 = "Шлифование материала сторона 1"
STAGE_SIDE2 = "Шлифование материала сторона 2"
STAGE_COAT_S1 = "Нанесение покрытия на материал слой 1 сторона 1"
STAGE_COAT_S2 = "Нанесение покрытия на материал слой 1 сторона 2"
STAGE_DRY = "Просушка нанесённого на материал покрытия"
STAGE_DRY_S1 = "Просушка нанесённого на материал покрытия сторона 1"
STAGE_DRY_S2 = "Просушка нанесённого на материал покрытия сторона 2"
STAGE_INTER1 = "Промежуточное шлифование после просушки 1 -го слоя покрытия"

QTY_SHEET = Decimal("1")
QTY_DISC_SIDE = Decimal("0.3")
QTY_PRIMER_SIDE = Decimal("0.05")
QTY_P320 = Decimal("0.2")
SAND_HOURS = Decimal("0.05")
SAND_EMP_MIN = Decimal("6")
COAT_HOURS = Decimal("0.05")
COAT_EMP_MIN = Decimal("4")
INTER_HOURS = Decimal("0.03")
INTER_EMP_MIN = Decimal("3")
DRY_HOURS = Decimal("1")
DRY_EMP_MIN = Decimal("2")
# Ожидание сушки — в «Затраты на производство», не как станок 500 ₽/ч.
DRY_OVERHEAD_PER_SIDE = Decimal("500")


def _norm(value: str) -> str:
    return (value or "").casefold().replace("ё", "е")


def _ensure_stage(ProductionStage, name, template=None, hourly_rate=None):
    stage = ProductionStage.objects.filter(name=name).first()
    if stage:
        if hourly_rate is not None and stage.hourly_rate != hourly_rate:
            stage.hourly_rate = hourly_rate
            stage.save(update_fields=["hourly_rate"])
        return stage
    rate = hourly_rate
    sequence = 1
    if rate is None and template is not None and template.hourly_rate is not None:
        rate = template.hourly_rate
    if rate is None:
        rate = Decimal("500")
    if template is not None:
        sequence = template.sequence or 1
    return ProductionStage.objects.create(
        name=name,
        sequence=sequence,
        hourly_rate=rate,
    )


def _set_process_stages(TechProcessStage, tech_process, stages):
    TechProcessStage.objects.filter(tech_process=tech_process).delete()
    for order, stage in enumerate(stages, start=1):
        TechProcessStage.objects.create(
            tech_process=tech_process,
            production_stage=stage,
            order=order,
        )


def _ensure_process(TechProcess, TechProcessStage, name, description, stages):
    tech_process = TechProcess.objects.filter(name=name).first()
    if tech_process is None:
        tech_process = TechProcess.objects.create(name=name, description=description)
    else:
        if (tech_process.description or "") != description:
            tech_process.description = description
            tech_process.save(update_fields=["description"])
    _set_process_stages(TechProcessStage, tech_process, stages)
    return tech_process


def _group_by_keyword(MaterialGroup, keyword, defaults):
    for existing in MaterialGroup.objects.all():
        if keyword in _norm(existing.name):
            return existing
    return MaterialGroup.objects.create(**defaults)


def _find_plywood_900_600_6(Material):
    for name in PLYWOOD_NAMES:
        row = Material.objects.filter(name=name, thickness_mm=Decimal("6")).first()
        if row:
            return row
    for row in Material.objects.filter(thickness_mm=Decimal("6")):
        name = _norm(row.name)
        if "фанера" in name and "900" in name and "600" in name and "сорт" in name:
            if "3мм" in name.replace(" ", "") or "4мм" in name.replace(" ", ""):
                continue
            if "шлиф" in name or "грунт" in name:
                continue
            return row
    return None


def _ensure_disc(Material, MaterialGroup, name):
    row = Material.objects.filter(name=name).first()
    if row:
        return row
    group = _group_by_keyword(
        MaterialGroup,
        "абразив",
        {"name": "Абразивы", "has_grade": False, "has_sheet_size": False},
    )
    return Material.objects.create(name=name, group=group, unit="шт", material_type="эксцентриковый")


def _ensure_product_group(ProductGroup, name):
    group, _ = ProductGroup.objects.get_or_create(name=name, defaults={"description": ""})
    return group


def _is_sanded_900_600_6(product) -> bool:
    name = _norm(product.name)
    if product.sheet_length_mm == Decimal("900") and product.sheet_width_mm == Decimal("600"):
        if product.sheet_thickness_mm in (Decimal("6"), 6):
            if "шлиф" in name:
                return True
    return product.name == SANDED_NAME


def _find_sanded_product(Product):
    exact = Product.objects.filter(name=SANDED_NAME).first()
    if exact:
        return exact
    for product in Product.objects.all():
        if _is_sanded_900_600_6(product):
            return product
    return None


def _find_card_a(TechCard, sanded):
    card = TechCard.objects.filter(name=CARD_A_NAME).first()
    if card:
        return card
    if sanded is None:
        return None
    for card in TechCard.objects.filter(product=sanded):
        name = _norm(card.name)
        if "таблич" in name:
            continue
        if "p120" in name and "двух сторон" in name:
            return card
    return None


def _replace_card_rows(TechCardItem, TechCardLaborLine, card, items, labor):
    TechCardItem.objects.filter(tech_card=card).delete()
    TechCardLaborLine.objects.filter(tech_card=card).delete()
    for row in items:
        TechCardItem.objects.create(tech_card=card, **row)
    for row in labor:
        TechCardLaborLine.objects.create(tech_card=card, **row)


def _sync_product_materials(ProductMaterial, product, quantities):
    ProductMaterial.objects.filter(product=product).delete()
    for material, qty in quantities:
        ProductMaterial.objects.create(
            product=product,
            material=material,
            quantity_per_unit=qty,
        )


def seed_fk_tech_cards(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    MaterialGroup = apps.get_model("core", "MaterialGroup")
    Product = apps.get_model("core", "Product")
    ProductGroup = apps.get_model("core", "ProductGroup")
    ProductLabor = apps.get_model("core", "ProductLabor")
    ProductMaterial = apps.get_model("core", "ProductMaterial")
    ProductionStage = apps.get_model("core", "ProductionStage")
    TechCard = apps.get_model("core", "TechCard")
    TechCardItem = apps.get_model("core", "TechCardItem")
    TechCardLaborLine = apps.get_model("core", "TechCardLaborLine")
    TechProcess = apps.get_model("core", "TechProcess")
    TechProcessStage = apps.get_model("core", "TechProcessStage")

    plywood = _find_plywood_900_600_6(Material)
    if plywood is None:
        return
    changed = []
    if plywood.sheet_length_mm != Decimal("900"):
        plywood.sheet_length_mm = Decimal("900")
        changed.append("sheet_length_mm")
    if plywood.sheet_width_mm != Decimal("600"):
        plywood.sheet_width_mm = Decimal("600")
        changed.append("sheet_width_mm")
    if plywood.unit != "лист":
        plywood.unit = "лист"
        changed.append("unit")
    if changed:
        plywood.save(update_fields=changed)

    p120 = _ensure_disc(Material, MaterialGroup, P120_NAME)
    p180 = _ensure_disc(Material, MaterialGroup, P180_NAME)
    p320 = Material.objects.filter(name=P320_NAME).first()
    if p320 is None:
        p320 = _ensure_disc(Material, MaterialGroup, P320_NAME)
    primer = Material.objects.filter(name=PRIMER_NAME).first()
    if primer is None:
        return

    side1 = _ensure_stage(ProductionStage, STAGE_SIDE1)
    side2 = _ensure_stage(ProductionStage, STAGE_SIDE2, template=side1)
    coat_s1 = _ensure_stage(ProductionStage, STAGE_COAT_S1, template=side1)
    coat_s2 = _ensure_stage(ProductionStage, STAGE_COAT_S2, template=side1)
    dry_s1 = _ensure_stage(ProductionStage, STAGE_DRY_S1, template=side1, hourly_rate=Decimal("0"))
    dry_s2 = _ensure_stage(ProductionStage, STAGE_DRY_S2, template=side1, hourly_rate=Decimal("0"))
    inter1 = _ensure_stage(ProductionStage, STAGE_INTER1, template=side1)

    process_a = _ensure_process(
        TechProcess,
        TechProcessStage,
        PROCESS_A_NAME,
        "Шлифование берёзовой ФК Ш2: P120, затем P180, сторона 1 и сторона 2.",
        [side1, side2],
    )
    process_b = _ensure_process(
        TechProcess,
        TechProcessStage,
        PROCESS_B_NAME,
        "Один слой грунта: сторона 1 → сушка → сторона 2 → сушка → P320. Сушка после каждой стороны отдельно.",
        [coat_s1, dry_s1, coat_s2, dry_s2, inter1],
    )

    group_sanded = _ensure_product_group(ProductGroup, GROUP_SANDED)
    group_primed = _ensure_product_group(ProductGroup, GROUP_PRIMED)

    sanded = _find_sanded_product(Product)
    if sanded is None:
        sanded = Product.objects.create(
            name=SANDED_NAME,
            product_kind="goods",
            product_group=group_sanded,
            unit="шт",
            sheet_length_mm=Decimal("900"),
            sheet_width_mm=Decimal("600"),
            sheet_thickness_mm=Decimal("6"),
        )
    Product.objects.filter(pk=sanded.pk).update(
        name=SANDED_NAME,
        product_kind="goods",
        product_group=group_sanded,
        unit="шт",
        sheet_length_mm=Decimal("900"),
        sheet_width_mm=Decimal("600"),
        sheet_thickness_mm=Decimal("6"),
    )
    sanded.refresh_from_db()
    if not (sanded.article or "").strip():
        Product.objects.filter(pk=sanded.pk).update(article=f"ART-{sanded.pk:06d}")
    ProductLabor.objects.filter(product=sanded).delete()

    primed = Product.objects.filter(name=PRIMED_NAME).first()
    if primed is None:
        primed = Product.objects.create(
            name=PRIMED_NAME,
            product_kind="goods",
            product_group=group_primed,
            unit="шт",
            sheet_length_mm=Decimal("900"),
            sheet_width_mm=Decimal("600"),
            sheet_thickness_mm=Decimal("6"),
        )
    Product.objects.filter(pk=primed.pk).update(
        name=PRIMED_NAME,
        product_kind="goods",
        product_group=group_primed,
        unit="шт",
        sheet_length_mm=Decimal("900"),
        sheet_width_mm=Decimal("600"),
        sheet_thickness_mm=Decimal("6"),
    )
    primed.refresh_from_db()
    if not (primed.article or "").strip():
        Product.objects.filter(pk=primed.pk).update(article=f"ART-{primed.pk:06d}")
    ProductLabor.objects.filter(product=primed).delete()

    card_a = _find_card_a(TechCard, sanded)
    if card_a is None:
        card_a = TechCard.objects.create(
            name=CARD_A_NAME,
            tech_process=process_a,
            product=sanded,
            card_group=group_sanded,
            labor_norm_input_unit="minutes",
            description="Сырой лист ФК 900×600×6 → шлифованный Ш2, P120 затем P180.",
        )
    else:
        TechCard.objects.filter(pk=card_a.pk).update(
            name=CARD_A_NAME,
            tech_process=process_a,
            product=sanded,
            card_group=group_sanded,
            labor_norm_input_unit="minutes",
            description="Сырой лист ФК 900×600×6 → шлифованный Ш2, P120 затем P180.",
        )
        card_a.refresh_from_db()

    _replace_card_rows(
        TechCardItem,
        TechCardLaborLine,
        card_a,
        [
            {
                "material": plywood,
                "product": None,
                "quantity": QTY_SHEET,
                "item_kind": "material",
                "production_stage": side1,
                "note": "Один лист на всю карту, на стороне 2 не дублировать",
            },
            {
                "material": p120,
                "product": None,
                "quantity": QTY_DISC_SIDE,
                "item_kind": "material",
                "production_stage": side1,
                "note": "Сторона 1",
            },
            {
                "material": p180,
                "product": None,
                "quantity": QTY_DISC_SIDE,
                "item_kind": "material",
                "production_stage": side1,
                "note": "Сторона 1",
            },
            {
                "material": p120,
                "product": None,
                "quantity": QTY_DISC_SIDE,
                "item_kind": "material",
                "production_stage": side2,
                "note": "Сторона 2",
            },
            {
                "material": p180,
                "product": None,
                "quantity": QTY_DISC_SIDE,
                "item_kind": "material",
                "production_stage": side2,
                "note": "Сторона 2",
            },
        ],
        [
            {
                "production_stage": side1,
                "norm_hours": SAND_HOURS,
                "employee_minutes": SAND_EMP_MIN,
            },
            {
                "production_stage": side2,
                "norm_hours": SAND_HOURS,
                "employee_minutes": SAND_EMP_MIN,
            },
        ],
    )
    _sync_product_materials(
        ProductMaterial,
        sanded,
        [
            (plywood, QTY_SHEET),
            (p120, QTY_DISC_SIDE * 2),
            (p180, QTY_DISC_SIDE * 2),
        ],
    )

    card_b = TechCard.objects.filter(name=CARD_B_NAME).first()
    if card_b is None:
        card_b = TechCard.objects.create(
            name=CARD_B_NAME,
            tech_process=process_b,
            product=primed,
            card_group=group_primed,
            labor_norm_input_unit="minutes",
            description="Шлифованный лист → грунт 1 слой с двух сторон, сушка, P320. Под морение, не второй слой.",
        )
    else:
        TechCard.objects.filter(pk=card_b.pk).update(
            name=CARD_B_NAME,
            tech_process=process_b,
            product=primed,
            card_group=group_primed,
            labor_norm_input_unit="minutes",
            description="Шлифованный лист → грунт 1 слой с двух сторон, сушка, P320. Под морение, не второй слой.",
        )
        card_b.refresh_from_db()

    _replace_card_rows(
        TechCardItem,
        TechCardLaborLine,
        card_b,
        [
            {
                "material": None,
                "product": sanded,
                "quantity": QTY_SHEET,
                "item_kind": "component",
                "production_stage": coat_s1,
                "component_tech_card": card_a,
                "composition_order": 1,
                "note": "Полуфабрикат с карты шлифования",
            },
            {
                "material": primer,
                "product": None,
                "quantity": QTY_PRIMER_SIDE,
                "item_kind": "material",
                "production_stage": coat_s1,
                "note": "Слой 1, сторона 1",
            },
            {
                "material": primer,
                "product": None,
                "quantity": QTY_PRIMER_SIDE,
                "item_kind": "material",
                "production_stage": coat_s2,
                "note": "Слой 1, сторона 2",
            },
            {
                "material": p320,
                "product": None,
                "quantity": QTY_P320,
                "item_kind": "material",
                "production_stage": inter1,
                "note": "Ворс после грунта, не протирать до сырого шпона",
            },
        ],
        [
            {
                "production_stage": coat_s1,
                "norm_hours": COAT_HOURS,
                "employee_minutes": COAT_EMP_MIN,
            },
            {
                "production_stage": dry_s1,
                "norm_hours": DRY_HOURS,
                "employee_minutes": DRY_EMP_MIN,
                "overhead_per_unit": DRY_OVERHEAD_PER_SIDE,
            },
            {
                "production_stage": coat_s2,
                "norm_hours": COAT_HOURS,
                "employee_minutes": COAT_EMP_MIN,
            },
            {
                "production_stage": dry_s2,
                "norm_hours": DRY_HOURS,
                "employee_minutes": DRY_EMP_MIN,
                "overhead_per_unit": DRY_OVERHEAD_PER_SIDE,
            },
            {
                "production_stage": inter1,
                "norm_hours": INTER_HOURS,
                "employee_minutes": INTER_EMP_MIN,
            },
        ],
    )
    _sync_product_materials(
        ProductMaterial,
        primed,
        [
            (primer, QTY_PRIMER_SIDE * 2),
            (p320, QTY_P320),
        ],
    )


def unseed_fk_tech_cards(apps, schema_editor):
    TechCard = apps.get_model("core", "TechCard")
    Product = apps.get_model("core", "Product")
    TechCard.objects.filter(name=CARD_B_NAME).delete()
    Product.objects.filter(name=PRIMED_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0116_seed_plywood_fk_4mm"),
    ]

    operations = [
        migrations.RunPython(seed_fk_tech_cards, unseed_fk_tech_cards),
    ]
