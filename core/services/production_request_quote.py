"""Черновой ориентир стоимости заявки на производство."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from core.models import ProductionRequest, ProductionStage
from core.services.layout_path_metrics import measure_layout_file


def _default_cut_rate() -> Decimal:
    rate = (
        ProductionStage.objects.exclude(cut_rate_per_meter__isnull=True)
        .exclude(cut_rate_per_meter=0)
        .order_by("sequence", "id")
        .values_list("cut_rate_per_meter", flat=True)
        .first()
    )
    if rate is not None:
        return Decimal(str(rate))
    return Decimal(str(getattr(settings, "QUOTE_DEFAULT_CUT_RATE_PER_M", "15")))


def _default_engrave_rate() -> Decimal:
    return Decimal(str(getattr(settings, "QUOTE_DEFAULT_ENGRAVE_RATE_PER_M", "8")))


def _personalization_fee(req: ProductionRequest) -> Decimal:
    if (req.engraving_text or "").strip() or req.logo_file:
        return Decimal(str(getattr(settings, "QUOTE_PERSONALIZATION_FEE", "250")))
    return Decimal("0")


def refresh_layout_metrics(req: ProductionRequest) -> None:
    if not req.layout_file:
        req.layout_cut_length_m = None
        req.layout_engrave_length_m = None
        req.layout_metrics_status = ProductionRequest.METRICS_NONE
        req.layout_metrics_note = ""
        return
    try:
        path = req.layout_file.path
    except Exception:
        req.layout_metrics_status = ProductionRequest.METRICS_ERROR
        req.layout_metrics_note = "Не удалось открыть файл макета"
        return
    metrics = measure_layout_file(path)
    req.layout_cut_length_m = metrics.cut_length_m
    req.layout_engrave_length_m = metrics.engrave_length_m
    req.layout_metrics_status = metrics.status
    req.layout_metrics_note = metrics.note[:500]


def apply_draft_quote(req: ProductionRequest) -> None:
    """Пересчитать ориентир цены и при необходимости метры из макета."""
    qty = max(1, int(req.quantity or 1))
    note_parts = ["Ориентировочная стоимость, уточняется менеджером."]

    if req.order_mode == ProductionRequest.ORDER_MODE_CUSTOM:
        refresh_layout_metrics(req)
        cut_m = req.layout_cut_length_m or Decimal("0")
        eng_m = req.layout_engrave_length_m or Decimal("0")
        if req.layout_metrics_status == ProductionRequest.METRICS_OK and (cut_m or eng_m):
            unit = (cut_m * _default_cut_rate()) + (eng_m * _default_engrave_rate())
            note_parts.append(
                f"По макету: рез {cut_m} м × {_default_cut_rate()} ₽/м, "
                f"гравировка {eng_m} м × {_default_engrave_rate()} ₽/м."
            )
        else:
            unit = Decimal("0")
            if req.layout_metrics_note:
                note_parts.append(req.layout_metrics_note)
            else:
                note_parts.append("Загрузите DXF или SVG для авторасчёта метров.")
    else:
        # Каталог: себестоимость изделия + доплата за персонализацию
        unit = Decimal("0")
        if req.product_id:
            try:
                unit = Decimal(str(req.product.planned_total_cost or 0))
            except Exception:
                unit = Decimal("0")
            note_parts.append("База — плановая себестоимость выбранного изделия.")
        else:
            note_parts.append("Изделие не выбрано — ориентир уточнит менеджер.")
        fee = _personalization_fee(req)
        if fee:
            unit += fee
            note_parts.append(f"Персонализация (текст/лого): +{fee} ₽/шт.")
        # Макет в каталожном режиме не обязателен; если DXF всё же приложили — посчитаем метры справочно
        if req.layout_file:
            refresh_layout_metrics(req)

    req.draft_unit_cost = unit.quantize(Decimal("0.01"))
    req.draft_total_cost = (unit * qty).quantize(Decimal("0.01"))
    req.draft_quoted_at = timezone.now()
    req.draft_quote_note = " ".join(note_parts)[:500]
