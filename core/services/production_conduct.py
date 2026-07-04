from decimal import Decimal

from django.apps import apps
from django.db.models import F


def _as_positive_decimal(value) -> Decimal:
    qty = Decimal(str(value or 0))
    if qty <= 0:
        return Decimal("0")
    return qty


def consume_material(*, warehouse, material_id: int, quantity, material_name: str = "") -> None:
    """
    Списать материал со склада с проверкой доступного остатка.
    Одновременно обновляет глобальный Material.current_stock.
    """
    qty = _as_positive_decimal(quantity)
    if qty <= 0:
        return

    MaterialStock = apps.get_model("core", "MaterialStock")
    Material = apps.get_model("core", "Material")

    stock, _ = MaterialStock.objects.get_or_create(
        warehouse=warehouse,
        material_id=material_id,
        defaults={"quantity": 0},
    )
    if stock.quantity < qty:
        if not material_name:
            material_name = (
                Material.objects.filter(pk=material_id).values_list("name", flat=True).first()
                or f"ID={material_id}"
            )
        raise ValueError(
            f"Недостаточно материала «{material_name}»: нужно {qty}, есть {stock.quantity}"
        )
    stock.quantity -= qty
    stock.save(update_fields=["quantity"])
    Material.objects.filter(pk=material_id).update(current_stock=F("current_stock") - qty)


def consume_product(
    *,
    warehouse,
    product_id: int,
    quantity,
    product_name: str = "",
    item_label: str = "полуфабриката",
) -> None:
    """Списать продукцию/полуфабрикат со склада с проверкой остатка."""
    qty = _as_positive_decimal(quantity)
    if qty <= 0:
        return

    ProductStock = apps.get_model("core", "ProductStock")
    Product = apps.get_model("core", "Product")

    stock, _ = ProductStock.objects.get_or_create(
        warehouse=warehouse,
        product_id=product_id,
        defaults={"quantity": 0},
    )
    if stock.quantity < qty:
        if not product_name:
            product_name = (
                Product.objects.filter(pk=product_id).values_list("name", flat=True).first()
                or f"ID={product_id}"
            )
        raise ValueError(
            f"Недостаточно {item_label} «{product_name}»: нужно {qty}, есть {stock.quantity}"
        )
    stock.quantity -= qty
    stock.save(update_fields=["quantity"])


def produce_material(*, warehouse, material_id: int, quantity) -> None:
    """Оприходовать материал на склад и обновить глобальный current_stock."""
    qty = _as_positive_decimal(quantity)
    if qty <= 0:
        return

    MaterialStock = apps.get_model("core", "MaterialStock")
    Material = apps.get_model("core", "Material")

    stock, _ = MaterialStock.objects.get_or_create(
        warehouse=warehouse,
        material_id=material_id,
        defaults={"quantity": 0},
    )
    stock.quantity += qty
    stock.save(update_fields=["quantity"])
    Material.objects.filter(pk=material_id).update(current_stock=F("current_stock") + qty)


def produce_product(*, warehouse, product_id: int, quantity) -> None:
    """Оприходовать продукцию на склад."""
    qty = _as_positive_decimal(quantity)
    if qty <= 0:
        return

    ProductStock = apps.get_model("core", "ProductStock")

    stock, _ = ProductStock.objects.get_or_create(
        warehouse=warehouse,
        product_id=product_id,
        defaults={"quantity": 0},
    )
    stock.quantity += qty
    stock.save(update_fields=["quantity"])

