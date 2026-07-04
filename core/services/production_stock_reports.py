"""Плановый выпуск по производственным заданиям для отчётов «Остатки» и закупок."""

from decimal import Decimal

from django.db.models import (
    DecimalField,
    F,
    OuterRef,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce, Greatest

from core.models import ProductionAssignment, ProductionAssignmentItem, ProductionDefect

DECIMAL_QTY = DecimalField(max_digits=16, decimal_places=3)

PRODUCTION_EXPECTATION_ASSIGNMENT_STATUSES = (
    ProductionAssignment.STATUS_DRAFT,
    ProductionAssignment.STATUS_IN_PROGRESS,
)


def _item_defect_subquery():
    """Сумма брака по позиции задания (OuterRef — ProductionAssignmentItem.pk)."""
    return Subquery(
        ProductionDefect.objects.filter(assignment_item_id=OuterRef("pk"))
        .values("assignment_item_id")
        .annotate(total=Sum("quantity"))
        .values("total")[:1],
        output_field=DECIMAL_QTY,
    )


def _pending_items_queryset(*, product_id=None, warehouse_id=None):
    """
    Позиции заданий с «Ожиданием», у которых ещё не выпущена часть плана.
    pending = max(0, quantity_planned − max(0, quantity_produced − defect)).
    """
    qs = ProductionAssignmentItem.objects.filter(
        assignment__expectation=True,
        assignment__status__in=PRODUCTION_EXPECTATION_ASSIGNMENT_STATUSES,
        tech_card__product_id__isnull=False,
    )
    if product_id is not None:
        qs = qs.filter(tech_card__product_id=product_id)
    if warehouse_id is not None:
        qs = qs.filter(assignment__product_warehouse_id=warehouse_id)
    return qs.annotate(
        _defect_qty=Coalesce(
            _item_defect_subquery(),
            Value(Decimal("0")),
            output_field=DECIMAL_QTY,
        ),
        _good_qty=Greatest(
            F("quantity_produced") - F("_defect_qty"),
            Value(Decimal("0")),
            output_field=DECIMAL_QTY,
        ),
        _pending_qty=Greatest(
            F("quantity_planned") - F("_good_qty"),
            Value(Decimal("0")),
            output_field=DECIMAL_QTY,
        ),
    ).filter(_pending_qty__gt=0)


def pending_production_quantity_subquery(*, product_lookup="pk", warehouse_lookup=None):
    """
    Subquery: суммарное «ожидание производства» по product_id.
    product_lookup — поле внешней модели (Product или ProductStock.product_id).
    warehouse_lookup — опционально поле склада (ProductStock.warehouse_id).
    """
    qs = _pending_items_queryset()
    if warehouse_lookup:
        qs = qs.filter(assignment__product_warehouse_id=OuterRef(warehouse_lookup))
    return Subquery(
        qs.filter(tech_card__product_id=OuterRef(product_lookup))
        .values("tech_card__product_id")
        .annotate(total=Sum("_pending_qty"))
        .values("total")[:1],
        output_field=DECIMAL_QTY,
    )


def pending_production_by_product(*, warehouse_id=None) -> dict[int, Decimal]:
    """Словарь product_id → количество в ожидании производства."""
    qs = _pending_items_queryset(warehouse_id=warehouse_id)
    rows = qs.values("tech_card__product_id").annotate(total=Sum("_pending_qty"))
    return {
        row["tech_card__product_id"]: row["total"]
        for row in rows
        if row["tech_card__product_id"] is not None and row["total"]
    }
