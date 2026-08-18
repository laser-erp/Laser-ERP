from decimal import Decimal

from django.db import migrations


def _norm(value):
    return (value or "").casefold().replace("ё", "е")


def _merge_stock_rows(model, from_id, to_id, item_field):
    for row in list(model.objects.filter(warehouse_id=from_id)):
        item_id = getattr(row, f"{item_field}_id")
        keeper = model.objects.filter(warehouse_id=to_id, **{f"{item_field}_id": item_id}).first()
        qty = row.quantity or Decimal("0")
        if keeper is None:
            row.warehouse_id = to_id
            row.save(update_fields=["warehouse"])
            continue
        keeper.quantity = (keeper.quantity or Decimal("0")) + qty
        keeper.save(update_fields=["quantity"])
        row.delete()


def remove_semifinished_warehouse(apps, schema_editor):
    Warehouse = apps.get_model("core", "Warehouse")
    warehouses = list(Warehouse.objects.all())
    semi = [row for row in warehouses if "полуфабрик" in _norm(row.name)]
    if not semi:
        return
    finished = next((row for row in warehouses if "готов" in _norm(row.name)), None)
    MaterialStock = apps.get_model("core", "MaterialStock")
    ProductStock = apps.get_model("core", "ProductStock")
    for junk in semi:
        if finished is not None and junk.id != finished.id:
            _merge_stock_rows(MaterialStock, junk.id, finished.id, "material")
            _merge_stock_rows(ProductStock, junk.id, finished.id, "product")
            for model in apps.get_models():
                if model._meta.label in {"core.MaterialStock", "core.ProductStock"}:
                    continue
                for field in model._meta.fields:
                    if not field.is_relation or field.many_to_many:
                        continue
                    rel = field.remote_field.model if field.remote_field else None
                    if rel is None:
                        continue
                    rel_label = getattr(getattr(rel, "_meta", None), "label", "") or ""
                    if rel_label != "core.Warehouse":
                        continue
                    model.objects.filter(**{field.name: junk}).update(**{field.name: finished})
                for field in model._meta.many_to_many:
                    rel = field.remote_field.model if field.remote_field else None
                    rel_label = getattr(getattr(rel, "_meta", None), "label", "") or ""
                    if rel_label != "core.Warehouse":
                        continue
                    through = field.remote_field.through
                    if through._meta.auto_created:
                        for obj in model.objects.filter(**{field.name: junk}):
                            getattr(obj, field.name).remove(junk)
                            getattr(obj, field.name).add(finished)
        MaterialStock.objects.filter(warehouse_id=junk.id).delete()
        ProductStock.objects.filter(warehouse_id=junk.id).delete()
        junk.delete()


def noop(apps, schema_editor):
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0126_remove_legacy_cutting_sheet_groups"),
    ]

    operations = [
        migrations.RunPython(remove_semifinished_warehouse, noop),
    ]
