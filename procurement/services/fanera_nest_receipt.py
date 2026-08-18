"""
Раскладка листа 1525×1525 (фанера-piter) → заготовки для строк приёмки.

С одного листа (лист + 150 ₽ распил): 3×900×600, 1×621×621, 1×317×900.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from django.apps import apps

SHEET_MM = Decimal("1525")
USED_AREA_MM2 = (
    Decimal("3") * Decimal("900") * Decimal("600")
    + Decimal("621") * Decimal("621")
    + Decimal("317") * Decimal("900")
)

NEST_THICKNESS_SPECS: dict[str, dict] = {
    "3": {
        "label": "3 мм",
        "sheet_price": Decimal("615"),
        "cut_price": Decimal("150"),
        "pieces": (
            (("900*600", "3мм"), 3),
            (("621*621", "3мм"), 1),
            (("317*900", "3мм"), 1),
        ),
    },
    "4": {
        "label": "4 мм",
        "sheet_price": Decimal("740"),
        "cut_price": Decimal("150"),
        "pieces": (
            (("900*600", "4мм"), 3),
            (("621*621", "4мм"), 1),
            (("317*900", "4мм"), 1),
        ),
    },
    "6": {
        "label": "6 мм",
        "sheet_price": Decimal("1030"),
        "cut_price": Decimal("150"),
        "pieces": (
            (("900*600", "6"), 3),
            (("621*621", "6"), 1),
            (("317*900", "6"), 1),
        ),
    },
}


@dataclass(frozen=True)
class NestReceiptLine:
    material_id: int
    material_name: str
    unit: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal

    def as_dict(self) -> dict:
        return {
            "material_id": self.material_id,
            "material_name": self.material_name,
            "unit": self.unit,
            "quantity": str(self.quantity),
            "unit_price": str(self.unit_price),
            "amount": str(self.amount),
        }


def _norm_catalog_text(value: str) -> str:
    return (value or "").casefold().replace("ё", "е").replace("×", "*").replace(" ", "")


def _find_material(name_parts: tuple[str, ...]):
    Material = apps.get_model("core", "Material")
    needles = [_norm_catalog_text(part) for part in name_parts if part]
    for material in Material.objects.filter(name__icontains="Фанера ФК").order_by("pk"):
        haystack = _norm_catalog_text(material.name)
        if all(needle in haystack for needle in needles):
            return material
    return None


def _piece_unit_price(
    *,
    sheet_price: Decimal,
    cut_price: Decimal,
    piece_area_mm2: Decimal,
) -> Decimal:
    total = sheet_price + cut_price
    return (total * piece_area_mm2 / USED_AREA_MM2).quantize(Decimal("0.0001"))


def _piece_area_from_markers(name_parts: tuple[str, ...]) -> Decimal:
    marker = _norm_catalog_text(name_parts[0] if name_parts else "")
    if "900*600" in marker:
        return Decimal("900") * Decimal("600")
    if "621*621" in marker:
        return Decimal("621") * Decimal("621")
    if "317*900" in marker:
        return Decimal("317") * Decimal("900")
    return Decimal("0")


def source_sheets_for_blanks(blanks_900x600: int) -> int:
    n = int(blanks_900x600)
    if n <= 0:
        return 0
    return math.ceil(n / 3)


def calc_nest_receipt_lines(
    *,
    thickness_mm: str = "3",
    source_sheets: int | None = None,
    blanks_900x600: int | None = None,
) -> tuple[list[NestReceiptLine], dict]:
    """
    Строки приёмки по комплекту с листа 1525×1525.

    Задайте source_sheets (сколько листов на фанере-piter) или blanks_900x600
    (сколько нужно заготовок 900×600 — листов посчитается с запасом).
    """
    spec = NEST_THICKNESS_SPECS.get(str(thickness_mm))
    if spec is None:
        raise ValueError(f"Неизвестная толщина: {thickness_mm}")

    sheets = int(source_sheets or 0)
    if blanks_900x600 is not None and int(blanks_900x600) > 0:
        sheets = source_sheets_for_blanks(int(blanks_900x600))
    if sheets <= 0:
        raise ValueError("Укажите число листов 1525×1525 или заготовок 900×600.")

    sheet_total = spec["sheet_price"] + spec["cut_price"]
    lines: list[NestReceiptLine] = []
    missing: list[str] = []

    for name_parts, qty_per_sheet in spec["pieces"]:
        material = _find_material(name_parts)
        area = _piece_area_from_markers(name_parts)
        fallback_price = _piece_unit_price(
            sheet_price=spec["sheet_price"],
            cut_price=spec["cut_price"],
            piece_area_mm2=area,
        )
        if material is None:
            missing.append(" / ".join(name_parts))
            unit_price = fallback_price
            material_id = 0
            material_name = f"Фанера ФК {' '.join(name_parts)} (нет в каталоге)"
            unit = "лист"
        else:
            material_id = material.pk
            material_name = material.name
            unit = (material.unit or "лист").strip() or "лист"
            if material.purchase_price is not None and material.purchase_price > 0:
                unit_price = Decimal(str(material.purchase_price)).quantize(Decimal("0.0001"))
            else:
                unit_price = fallback_price

        qty = (Decimal(qty_per_sheet) * Decimal(sheets)).quantize(Decimal("0.0001"))
        amount = (qty * unit_price).quantize(Decimal("0.01"))
        lines.append(
            NestReceiptLine(
                material_id=material_id,
                material_name=material_name,
                unit=unit,
                quantity=qty,
                unit_price=unit_price,
                amount=amount,
            )
        )

    grand = sum((line.amount for line in lines), Decimal("0")).quantize(Decimal("0.01"))
    meta = {
        "thickness_mm": str(thickness_mm),
        "thickness_label": spec["label"],
        "source_sheets": sheets,
        "sheet_price": str(spec["sheet_price"]),
        "cut_price": str(spec["cut_price"]),
        "sheet_total": str(sheet_total),
        "receipt_total": str(grand),
        "shop_total": str((sheet_total * Decimal(sheets)).quantize(Decimal("0.01"))),
        "blanks_900x600": sheets * 3,
        "missing_materials": missing,
    }
    return lines, meta


def build_nest_kits_payload() -> dict:
    """JSON для калькулятора на форме приёмки."""
    kits = []
    for key, spec in NEST_THICKNESS_SPECS.items():
        pieces = []
        for name_parts, qty_per_sheet in spec["pieces"]:
            material = _find_material(name_parts)
            area = _piece_area_from_markers(name_parts)
            fallback = _piece_unit_price(
                sheet_price=spec["sheet_price"],
                cut_price=spec["cut_price"],
                piece_area_mm2=area,
            )
            pieces.append(
                {
                    "qty_per_sheet": qty_per_sheet,
                    "material_id": material.pk if material else None,
                    "material_name": material.name if material else " / ".join(name_parts),
                    "unit": (material.unit or "лист").strip() if material else "лист",
                    "unit_price": str(
                        Decimal(str(material.purchase_price)).quantize(Decimal("0.0001"))
                        if material and material.purchase_price
                        else fallback
                    ),
                }
            )
        kits.append(
            {
                "thickness_mm": key,
                "label": spec["label"],
                "sheet_price": str(spec["sheet_price"]),
                "cut_price": str(spec["cut_price"]),
                "sheet_total": str(spec["sheet_price"] + spec["cut_price"]),
                "pieces": pieces,
            }
        )
    return {"kits": kits, "nest_note": "1 лист 1525×1525 → 3×900×600 + 621×621 + 317×900"}
