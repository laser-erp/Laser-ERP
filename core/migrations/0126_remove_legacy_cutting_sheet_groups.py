from django.db import migrations

# Старые группы «лист для резки …» — путаница со шлифованным/грунтованным товаром.
JUNK_GROUP_NAMES = {
    "лист шлифованный",
    "лист грунтованный",
    "лист тонированый",
    "лист тонированный",
}


def _norm(value):
    return (value or "").casefold().replace("ё", "е").strip()


def _is_junk_group_name(name):
    return _norm(name) in JUNK_GROUP_NAMES


def _is_junk_material_name(name):
    text = _norm(name)
    if not text.startswith("лист для резки"):
        return False
    return any(token in text for token in ("шлифован", "грунтован", "тонирован"))


def _related_qs(apps, app_label, model_name, **filter_kwargs):
    try:
        model = apps.get_model(app_label, model_name)
    except LookupError:
        return None
    return model.objects.filter(**filter_kwargs)


def _clear_or_delete(apps, app_label, model_name, material_ids, field="material", allow_null=False):
    qs = _related_qs(apps, app_label, model_name, **{f"{field}__in": material_ids})
    if qs is None:
        return
    if allow_null:
        qs.update(**{field: None})
    else:
        qs.delete()


def remove_legacy_cutting_sheet_groups(apps, schema_editor):
    MaterialGroup = apps.get_model("core", "MaterialGroup")
    Material = apps.get_model("core", "Material")
    Product = apps.get_model("core", "Product")

    groups = [group for group in MaterialGroup.objects.all() if _is_junk_group_name(group.name)]
    group_ids = [group.id for group in groups]
    material_ids = [
        row.id
        for row in Material.objects.all()
        if row.group_id in group_ids or _is_junk_material_name(row.name)
    ]
    if not material_ids and not group_ids:
        return

    if material_ids:
        Product.objects.filter(material_group_id__in=group_ids).update(material_group=None)
        _clear_or_delete(apps, "core", "MaterialStock", material_ids)
        _clear_or_delete(apps, "core", "MaterialBatch", material_ids)
        _clear_or_delete(apps, "core", "ProductMaterial", material_ids)
        _clear_or_delete(apps, "core", "TechCardItem", material_ids)
        _clear_or_delete(apps, "core", "TechOperationMaterial", material_ids)
        _clear_or_delete(apps, "core", "AssignmentMaterialReservation", material_ids)
        _clear_or_delete(apps, "core", "MaterialReservation", material_ids)
        _clear_or_delete(apps, "core", "ProductionMaterialUsage", material_ids)
        _clear_or_delete(apps, "core", "ProductionDeviation", material_ids, allow_null=True)
        _clear_or_delete(apps, "procurement", "GoodsReceiptLine", material_ids, allow_null=True)
        _clear_or_delete(apps, "procurement", "SupplierOrderLine", material_ids, allow_null=True)
        Material.objects.filter(id__in=material_ids).delete()

    Product.objects.filter(material_group_id__in=group_ids).update(material_group=None)
    MaterialGroup.objects.filter(id__in=group_ids).delete()


def noop(apps, schema_editor):
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0125_seed_fk_3mm_goods"),
        ("procurement", "0005_goods_receipt_po_product"),
    ]

    operations = [
        migrations.RunPython(remove_legacy_cutting_sheet_groups, noop),
    ]
