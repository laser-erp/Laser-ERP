"""
Синхронизация номенклатуры Product (вид «Материал») со складским справочником Material.

Техкарта и модальное окно выбора материалов работают только с core.Material;
поле Product.material_group задаёт ту же MaterialGroup — при сохранении подтягиваем строку в справочник.
"""
from __future__ import annotations

from django.db import transaction

from core.models import Material, Product


def sync_catalog_material_from_product_nomenclature(product: Product) -> None:
    if product.product_kind != Product.PRODUCT_KIND_MATERIAL:
        return
    name = (product.name or "").strip()
    if not name:
        return
    name = name[: Material._meta.get_field("name").max_length]
    unit = ((product.unit or "").strip() or "шт")[: Material._meta.get_field("unit").max_length]

    with transaction.atomic():
        m = Material.objects.filter(name__iexact=name).order_by("pk").first()
        if m:
            m.group_id = product.material_group_id
            m.unit = unit or m.unit
            m.save(update_fields=["group", "unit"])
        else:
            Material.objects.create(
                name=name,
                group_id=product.material_group_id,
                unit=unit,
            )
