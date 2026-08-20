from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
import re
from urllib.parse import urlencode

from django import forms
from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.widgets import AdminFileWidget
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Count, DecimalField, F, Max, OuterRef, Prefetch, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponseNotAllowed, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import NoReverseMatch, path, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.core.files.base import ContentFile

from .admin_mixins import ReturnToReferrerMixin
from .services.bank_bik import fetch_bank_details_by_bik
from .services.fns import fetch_contragents, fetch_contragent_egr_payload
from .services.material_nomenclature_sync import sync_catalog_material_from_product_nomenclature
from .services.production_stock_reports import pending_production_quantity_subquery
from .widgets import UnitDatalistTextWidget


def _admin_change_url_for_db_table(model, pk, prefer_app_label: str) -> str:
    """URL правки в админке для модели с тем же db_table (core vs production-прокси)."""
    if not pk:
        return ""
    table = model._meta.db_table
    candidates = []
    for reg_model in admin.site._registry:
        if reg_model._meta.db_table != table:
            continue
        candidates.append(reg_model)
    candidates.sort(
        key=lambda m: (
            0 if m._meta.app_label == prefer_app_label else 1,
            m._meta.label,
        )
    )
    for m in candidates:
        try:
            return reverse(
                f"admin:{m._meta.app_label}_{m._meta.model_name}_change",
                args=[pk],
            )
        except NoReverseMatch:
            continue
    return ""


admin.site.site_header = "Система учёта лазерного производства"
admin.site.site_title = "Администрирование Laser ERP"
admin.site.index_title = "Управление данными"

from .models import (
    PACKAGING_UNITS,
    PLYWOOD_GRADES,
    SHEET_UNITS,
    build_abrasive_name,
    looks_like_abrasive_name,
    normalize_abrasive_grit,
    ExpenseLedgerEntry,
    Contract,
    ContractVersion,
    BankPaymentOrder,
    CustomerInvoice,
    AdminInvite,
    EmailVerification,
    Employee,
    LaborTimeLog,
    Material,
    MaterialBatch,
    MaterialGroup,
    MaterialGroupBrand,
    MaterialGroupColor,
    MaterialGroupDiameter,
    MaterialGroupGrit,
    MaterialGroupHoleCount,
    MaterialGroupType,
    MaterialReservation,
    OperationType,
    Order,
    OrderItem,
    Organization,
    PriceList,
    PriceListColumn,
    PriceListEntry,
    ProductionRequest,
    ProductionRequestMessage,
    Product,
    ProductGalleryImage,
    ProductAnalog,
    ProductBarcode,
    ProductModification,
    ProductDisassembly,
    ProductGroup,
    ProductLabor,
    ServiceGroup,
    ProductMaterial,
    ProductionAssignment,
    ProductionAssignmentItem,
    ProductionBatch,
    ProductionDefect,
    ProductionDeviation,
    ProductionMaterialUsage,
    ProductionOrder,
    ProductionStage,
    ProductionStageCounterpartyService,
    ProductStock,
    MaterialStock,
    TechCard,
    TechOperation,
    TechProcess,
    TechProcessStage,
    UserProfile,
    Warehouse,
)
from procurement.models import GoodsReceipt, ReceivedVatInvoice, SupplierInvoice


def _organization_supplier_queryset(request, instance_model, supplier_field="supplier"):
    """Контрагенты с ролью «Поставщик»; при правке включает текущее значение FK."""
    sid_field = f"{supplier_field}_id"
    q = Q(is_supplier=True)
    rm = getattr(request, "resolver_match", None)
    oid = rm.kwargs.get("object_id") if rm and rm.kwargs else None
    if oid:
        try:
            sid = (
                instance_model.objects.filter(pk=int(oid))
                .values_list(sid_field, flat=True)
                .first()
            )
            if sid:
                q |= Q(pk=sid)
        except (ValueError, TypeError):
            pass
    return Organization.objects.filter(q).distinct().order_by("name")


def _material_average_unit_prices_map():
    """
    Цена закупки по материалу для расчёта себестоимости.
    Сначала закупочная с карточки, затем средняя по приёмкам (IN) перекрывает её.
    """
    out = {}
    for row in Material.objects.exclude(purchase_price__isnull=True).values("id", "purchase_price"):
        price = row["purchase_price"]
        if price is not None and price > 0:
            out[str(row["id"])] = format(Decimal(str(price)).quantize(Decimal("0.0001")), "f")
    rows = (
        MaterialBatch.objects.filter(movement_type=MaterialBatch.INCOMING)
        .values("material_id")
        .annotate(tq=Sum("quantity"), tc=Sum(F("quantity") * F("unit_price")))
    )
    for row in rows:
        tq, tc = row["tq"], row["tc"]
        if tq and tc:
            avg = (tc / tq).quantize(Decimal("0.0001"))
            out[str(row["material_id"])] = format(avg, "f")
    return out


# Регистрация только для autocomplete (раздел «Производство» — прокси в production)
@admin.register(TechCard)
class TechCardAutocompleteAdmin(admin.ModelAdmin):
    search_fields = ("name", "description", "card_group__name")

    def get_model_perms(self, request):
        return {}  # не показывать в списке приложений


@admin.register(TechOperation)
class TechOperationAutocompleteAdmin(admin.ModelAdmin):
    def get_model_perms(self, request):
        return {}  # не показывать в списке приложений


@admin.action(description="Копировать выбранные материалы")
def copy_materials(modeladmin, request, queryset):
    created = 0
    for material in queryset:
        new_name = f"Копия: {material.name}"[:255]
        if Material.objects.filter(name=new_name).exists():
            suffix = 1
            while Material.objects.filter(name=f"{new_name} ({suffix})").exists():
                suffix += 1
            new_name = f"{new_name} ({suffix})"[:255]
        Material.objects.create(
            name=new_name,
            group=material.group,
            material_type=material.material_type,
            thickness_mm=material.thickness_mm,
            sheet_length_mm=material.sheet_length_mm,
            sheet_width_mm=material.sheet_width_mm,
            unit=material.unit,
            grade=material.grade,
            current_stock=0,
            photo=material.photo,
            brand=material.brand,
            color=material.color,
            grit=material.grit,
            diameter_mm=material.diameter_mm,
            hole_count=material.hole_count,
        )
        created += 1
    messages.success(request, f"Создано копий: {created}.")


class MaterialPhotoWidget(AdminFileWidget):
    """Миниатюра и кнопки «Заменить» / «Удалить», без длинного пути к файлу."""

    template_name = "admin/widgets/material_photo.html"

    def build_attrs(self, base_attrs, extra_attrs=None):
        attrs = super().build_attrs(base_attrs, extra_attrs)
        css = attrs.get("class", "")
        extra = "file-upload-input laser-file-input-native"
        missing = [cls for cls in extra.split() if cls not in css.split()]
        if missing:
            attrs["class"] = f"{css} {' '.join(missing)}".strip()
        return attrs

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        preview_url = ""
        if value and getattr(value, "name", None):
            try:
                preview_url = value.url
            except (ValueError, OSError):
                preview_url = ""
        context["widget"]["preview_url"] = preview_url
        return context


class MaterialAdminForm(forms.ModelForm):
    class Meta:
        model = Material
        exclude = ("current_stock",)
        widgets = {
            "photo": MaterialPhotoWidget,
        }
        labels = {
            "material_type": "Тип",
            "brand": "Бренд",
            "color": "Цвет",
            "grit": "Зерно",
            "diameter_mm": "Диаметр, мм",
            "hole_count": "Отверстия",
            "grade": "Сорт",
            "sheet_length_mm": "Д×Ш×Т",
            "sheet_width_mm": "Ш",
            "thickness_mm": "Т",
        }
        help_texts = {
            "name": (
                "Как материал будет называться в справочнике, в техкарте и в приёмке. "
                "Для морилки имя собирается из бренда и цвета, например: "
                "Морилка водная Tury «Дуб»."
            ),
            "group": (
                "Раздел справочника (Фанера, Акрил, Металл и т.п.) — для фильтра в списке "
                "и в меню склада. Можно не заполнять. Новую группу добавляют кнопкой «+» "
                "рядом с полем."
            ),
            "material_type": (
                "Короткий тип для поиска и фильтра. Список зависит от группы: "
                "для фанеры — ФК, ФСФ; для абразивов — эксцентриковый, ленточный."
            ),
            "brand": (
                "Кнопка «+» добавляет бренд в список группы. "
                "Для морилки и абразива участвует в наименовании карточки."
            ),
            "color": (
                "Цвет морилки (дуб, орех…). Кнопка «+» добавляет цвет в список группы. "
                "У бесцветного лака поле скрыто."
            ),
            "grit": (
                "Зерно абразива, например P120. Кнопка «+» добавляет значение в список группы."
            ),
            "diameter_mm": (
                "Диаметр круга в миллиметрах (125, 150). Для ленточного типа поле скрыто."
            ),
            "hole_count": (
                "Число отверстий пылеудаления. Для ленточного типа поле скрыто."
            ),
            "grade": (
                "Сорт фанеры по ГОСТ, например 1/2, 2/2, 3/4. "
                "Поле видно, если у группы включено «Указывать сорт»."
            ),
            "unit": (
                "В каких единицах ведёте остаток и расход. Для упаковки обычно шт, м, рулон, кг. "
                "Для листовых — лист или м²."
            ),
            "purchase_price": (
                "Цена за единицу с чека. Пока нет проведённых приёмок, техкарта берёт эту цену. "
                "После приёмки себестоимость считается по средней цене поступлений."
            ),
            "sheet_length_mm": (
                "Укажите Длину, Ширину и Толщину листа для расчёта площади."
            ),
            "sheet_width_mm": "",
            "thickness_mm": "",
            "sheet_geometry_preview": (
                "Считается автоматически из длины × ширины. "
                "Показывается в м², см² и мм². Если длина или ширина не заданы — площадь не считается."
            ),
            "photo": (
                "Необязательное фото материала. Показывается в списке и в карточке. "
                "На остаток и цены не влияет."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        group = None
        if self.is_bound:
            raw_group = self.data.get(self.add_prefix("group"))
            if raw_group:
                try:
                    group = MaterialGroup.objects.prefetch_related(
                        "type_choices",
                        "brand_choices",
                        "color_choices",
                        "grit_choices",
                        "diameter_choices",
                        "hole_choices",
                    ).get(pk=int(raw_group))
                except (TypeError, ValueError, MaterialGroup.DoesNotExist):
                    group = None
        elif self.instance and getattr(self.instance, "group_id", None):
            group = getattr(self.instance, "group", None)
        type_choices = ()
        unit_choices = SHEET_UNITS
        grade_choices = ()
        brand_choices = ()
        color_choices = ()
        grit_choices = ()
        diameter_choices = ()
        hole_choices = ()
        if group is not None:
            type_choices = tuple(
                group.type_choices.order_by("sort_order", "name").values_list("name", flat=True)
            )
            unit_choices = PACKAGING_UNITS if not group.has_sheet_size else SHEET_UNITS
            if group.has_grade:
                grade_choices = PLYWOOD_GRADES
            if group.has_brand:
                brand_choices = tuple(
                    group.brand_choices.order_by("sort_order", "name").values_list("name", flat=True)
                )
            if group.has_color:
                color_choices = tuple(
                    group.color_choices.order_by("sort_order", "name").values_list("name", flat=True)
                )
            if group.has_grit:
                grit_choices = tuple(
                    group.grit_choices.order_by("sort_order", "name").values_list("name", flat=True)
                )
            if group.has_diameter:
                diameter_choices = tuple(
                    group.diameter_choices.order_by("sort_order", "name").values_list("name", flat=True)
                )
            if group.has_hole_count:
                hole_choices = tuple(
                    group.hole_choices.order_by("sort_order", "name").values_list("name", flat=True)
                )
        self._setup_choice_select("material_type", type_choices)
        self._setup_choice_select("unit", unit_choices)
        self._setup_choice_select("grade", grade_choices)
        self._setup_choice_select("brand", brand_choices)
        self._setup_choice_select("color", color_choices)
        self._setup_choice_select("grit", grit_choices)
        self._setup_choice_select("diameter_mm", diameter_choices)
        self._setup_choice_select("hole_count", hole_choices)
        if "name" in self.fields:
            self.fields["name"].required = False
        if "sheet_length_mm" in self.fields:
            self.fields["sheet_length_mm"].widget.attrs.setdefault("title", "Длина, мм")
        if "sheet_width_mm" in self.fields:
            self.fields["sheet_width_mm"].widget.attrs.setdefault("title", "Ширина, мм")
        if "thickness_mm" in self.fields:
            self.fields["thickness_mm"].widget.attrs.setdefault("title", "Толщина, мм")

    def clean(self):
        cleaned = super().clean()
        material_type = str(cleaned.get("material_type") or "").strip()
        brand = str(cleaned.get("brand") or "").strip()
        color = str(cleaned.get("color") or "").strip()
        grit = normalize_abrasive_grit(cleaned.get("grit") or "")
        diameter_mm = str(cleaned.get("diameter_mm") or "").strip()
        hole_count = str(cleaned.get("hole_count") or "").strip()
        name = str(cleaned.get("name") or "").strip()
        type_n = material_type.casefold().replace("ё", "е")
        is_stain = "морилк" in type_n
        is_belt = "лент" in type_n
        group = cleaned.get("group")
        use_abrasive = bool(group and getattr(group, "has_grit", False))
        if not is_stain:
            color = ""
        auto_name = ""
        if is_stain and brand and color:
            auto_name = f"Морилка водная {brand} «{color}»"
        elif use_abrasive:
            auto_name = build_abrasive_name(
                material_type=material_type,
                brand=brand,
                grit=grit,
                diameter_mm="" if is_belt else diameter_mm,
                hole_count="" if is_belt else hole_count,
            )
        stain_like = bool(re.match(r"^Морилка водная .+ «.+»$", name))
        abrasive_like = looks_like_abrasive_name(name)
        if auto_name and not name:
            name = auto_name
        elif auto_name and (stain_like or abrasive_like):
            if name.casefold().replace("ё", "е") != auto_name.casefold().replace("ё", "е"):
                name = auto_name
        if not name:
            self.add_error(
                "name",
                "Укажите наименование или заполните бренд и зерно (для морилки — бренд и цвет).",
            )
        cleaned["brand"] = brand
        cleaned["color"] = color
        cleaned["grit"] = grit
        cleaned["diameter_mm"] = diameter_mm
        cleaned["hole_count"] = hole_count
        cleaned["name"] = name
        return cleaned

    def _setup_choice_select(self, field_name, preset):
        field = self.fields.get(field_name)
        if field is None:
            return
        current = ""
        if self.is_bound:
            current = str(self.data.get(self.add_prefix(field_name)) or "").strip()
        elif self.instance is not None:
            current = str(getattr(self.instance, field_name, "") or "").strip()
        choices = [("", "—")]
        seen = {""}
        for value in list(preset or ()) + ([current] if current else []):
            if value not in seen:
                seen.add(value)
                choices.append((value, value))
        field.widget = forms.Select(attrs={"class": "material-choice-select"})
        field.widget.choices = choices


def _material_group_meta_payload(group=None):
    """JSON для карточки материала: типы, ед., сорт, бренд, цвет, зерно абразива."""
    empty = {
        "types": [],
        "has_grade": False,
        "grades": [],
        "has_sheet_size": True,
        "units": list(SHEET_UNITS),
        "has_brand": False,
        "brands": [],
        "has_color": False,
        "colors": [],
        "has_grit": False,
        "grits": [],
        "has_diameter": False,
        "diameters": [],
        "has_hole_count": False,
        "holes": [],
    }
    if group is None:
        return empty
    has_sheet = bool(group.has_sheet_size)
    payload = {
        **empty,
        "types": list(group.type_choices.order_by("sort_order", "name").values_list("name", flat=True)),
        "has_grade": bool(group.has_grade),
        "grades": list(PLYWOOD_GRADES) if group.has_grade else [],
        "has_sheet_size": has_sheet,
        "units": list(PACKAGING_UNITS if not has_sheet else SHEET_UNITS),
        "has_brand": bool(group.has_brand),
        "has_color": bool(group.has_color),
        "has_grit": bool(group.has_grit),
        "has_diameter": bool(group.has_diameter),
        "has_hole_count": bool(group.has_hole_count),
    }
    if group.has_brand:
        payload["brands"] = list(
            group.brand_choices.order_by("sort_order", "name").values_list("name", flat=True)
        )
    if group.has_color:
        payload["colors"] = list(
            group.color_choices.order_by("sort_order", "name").values_list("name", flat=True)
        )
    if group.has_grit:
        payload["grits"] = list(
            group.grit_choices.order_by("sort_order", "name").values_list("name", flat=True)
        )
    if group.has_diameter:
        payload["diameters"] = list(
            group.diameter_choices.order_by("sort_order", "name").values_list("name", flat=True)
        )
    if group.has_hole_count:
        payload["holes"] = list(
            group.hole_choices.order_by("sort_order", "name").values_list("name", flat=True)
        )
    return payload


def _card_param_text(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, Decimal):
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text or "0"
    text = str(value).strip()
    return text if text else "—"


def _card_sheet_size_text(material) -> str:
    parts = []
    for value in (material.sheet_length_mm, material.sheet_width_mm, material.thickness_mm):
        if value is None:
            continue
        parts.append(_card_param_text(value))
    if not parts:
        return "—"
    return "×".join(parts) + " мм"


def material_card_group_params(material) -> list[tuple[str, str]]:
    """Параметры карточки списка: те же поля, что у группы на форме материала."""
    group = getattr(material, "group", None)
    type_name = str(getattr(material, "material_type", "") or "").strip()
    type_n = type_name.casefold().replace("ё", "е")
    is_stain = "морилк" in type_n
    is_belt = "лент" in type_n
    items: list[tuple[str, str]] = []
    if group is None:
        if type_name:
            items.append(("тип", type_name))
        return items
    items.append(("тип", _card_param_text(type_name)))
    if group.has_brand:
        items.append(("бренд", _card_param_text(material.brand)))
    if group.has_color and is_stain:
        items.append(("цвет", _card_param_text(material.color)))
    if group.has_grit:
        items.append(("зерно", _card_param_text(material.grit)))
    if group.has_diameter and not is_belt:
        diameter = _card_param_text(material.diameter_mm)
        items.append(("Ø", "—" if diameter == "—" else f"{diameter} мм"))
    if group.has_hole_count and not is_belt:
        items.append(("отв.", _card_param_text(material.hole_count)))
    if group.has_grade:
        items.append(("сорт", _card_param_text(material.grade)))
    if group.has_sheet_size:
        items.append(("лист", _card_sheet_size_text(material)))
        area = getattr(material, "area_m2", None)
        items.append(
            (
                "пл.",
                "—" if area is None else f"{_card_param_text(area.quantize(Decimal('0.0001')))} м²",
            )
        )
    return items


def _product_sheet_size_text(product) -> str:
    parts = []
    for value in (
        getattr(product, "sheet_length_mm", None),
        getattr(product, "sheet_width_mm", None),
        getattr(product, "sheet_thickness_mm", None),
    ):
        if value is None:
            continue
        parts.append(_card_param_text(value))
    if not parts:
        return "—"
    return "×".join(parts) + " мм"


def product_card_params(product) -> list[tuple[str, str]]:
    """Чипы карточки готовой продукции: артикул, лист, площадь, цена."""
    items: list[tuple[str, str]] = []
    article = str(getattr(product, "article", "") or "").strip()
    if article:
        items.append(("арт.", article))
    size = _product_sheet_size_text(product)
    if size != "—":
        items.append(("лист", size))
    area = getattr(product, "area_m2_manual", None)
    if area is not None:
        items.append(("пл.", f"{_card_param_text(area.quantize(Decimal('0.01')))} м²"))
    price = getattr(product, "planned_price", None)
    if price is None:
        price = getattr(product, "purchase_price", None)
    if price is not None:
        items.append(("цена", f"{_card_param_text(price)} ₽"))
    return items


_GROUP_CHOICE_MODELS = {
    "type": (MaterialGroupType, None, "material_type"),
    "brand": (MaterialGroupBrand, "has_brand", "brand"),
    "color": (MaterialGroupColor, "has_color", "color"),
    "grit": (MaterialGroupGrit, "has_grit", "grit"),
    "diameter": (MaterialGroupDiameter, "has_diameter", "diameter_mm"),
    "holes": (MaterialGroupHoleCount, "has_hole_count", "hole_count"),
}


def _ensure_material_group_choice(group, kind, name):
    """Добавляет тип/бренд/цвет в список группы. Возвращает каноническое имя."""
    label = str(name or "").strip()[:100]
    if group is None or not label or kind not in _GROUP_CHOICE_MODELS:
        return ""
    model, flag_name, _field = _GROUP_CHOICE_MODELS[kind]
    if flag_name and not getattr(group, flag_name, False):
        setattr(group, flag_name, True)
        group.save(update_fields=[flag_name])
    existing = model.objects.filter(group=group, name__iexact=label).first()
    if existing:
        return existing.name
    max_order = model.objects.filter(group=group).aggregate(m=Max("sort_order"))["m"]
    model.objects.create(group=group, name=label, sort_order=(max_order or 0) + 1)
    return label


def _rename_material_group_choice(group, kind, old_name, new_name):
    """Переименовывает пункт списка группы и подтягивает карточки материалов."""
    old_label = str(old_name or "").strip()[:100]
    new_label = str(new_name or "").strip()[:100]
    if group is None or kind not in _GROUP_CHOICE_MODELS or not old_label:
        return ""
    if not new_label or old_label.casefold() == new_label.casefold():
        row = _GROUP_CHOICE_MODELS[kind][0].objects.filter(group=group, name__iexact=old_label).first()
        return row.name if row else old_label
    model, _flag, material_field = _GROUP_CHOICE_MODELS[kind]
    row = model.objects.filter(group=group, name__iexact=old_label).first()
    if row is None:
        return _ensure_material_group_choice(group, kind, new_label)
    clash = model.objects.filter(group=group, name__iexact=new_label).exclude(pk=row.pk).first()
    canonical = clash.name if clash is not None else new_label
    Material.objects.filter(group=group).filter(**{f"{material_field}__iexact": old_label}).update(
        **{material_field: canonical}
    )
    if clash is not None:
        row.delete()
        return canonical
    row.name = canonical
    row.save(update_fields=["name"])
    return canonical


def material_group_flag_chips(group) -> list[str]:
    """Подписи включённых полей группы — как чипы на карточке списка."""
    if group is None:
        return []
    chips = []
    for attr, label in (
        ("has_grade", "сорт"),
        ("has_sheet_size", "лист"),
        ("has_brand", "бренд"),
        ("has_color", "цвет"),
        ("has_grit", "зерно"),
        ("has_diameter", "Ø"),
        ("has_hole_count", "отв."),
    ):
        if getattr(group, attr, False):
            chips.append(label)
    return chips


class MaterialGroupAdminForm(forms.ModelForm):
    class Meta:
        model = MaterialGroup
        fields = (
            "name",
            "has_grade",
            "has_sheet_size",
            "has_brand",
            "has_color",
            "has_grit",
            "has_diameter",
            "has_hole_count",
            "description",
        )
        labels = {
            "has_grade": "Сорт",
            "has_sheet_size": "Размеры листа",
            "has_brand": "Бренд",
            "has_color": "Цвет",
            "has_grit": "Зерно",
            "has_diameter": "Диаметр",
            "has_hole_count": "Отверстия",
        }


class MaterialGroupTypeInline(admin.TabularInline):
    model = MaterialGroupType
    extra = 1
    fields = ("name",)
    verbose_name = "Тип"
    verbose_name_plural = "Типы"


class MaterialGroupBrandInline(admin.TabularInline):
    model = MaterialGroupBrand
    extra = 1
    fields = ("name",)
    verbose_name = "Бренд"
    verbose_name_plural = "Бренды"


class MaterialGroupColorInline(admin.TabularInline):
    model = MaterialGroupColor
    extra = 1
    fields = ("name",)
    verbose_name = "Цвет"
    verbose_name_plural = "Цвета"


class MaterialGroupGritInline(admin.TabularInline):
    model = MaterialGroupGrit
    extra = 1
    fields = ("name",)
    verbose_name = "Зерно"
    verbose_name_plural = "Зерно"


class MaterialGroupDiameterInline(admin.TabularInline):
    model = MaterialGroupDiameter
    extra = 1
    fields = ("name",)
    verbose_name = "Диаметр"
    verbose_name_plural = "Диаметры"


class MaterialGroupHoleCountInline(admin.TabularInline):
    model = MaterialGroupHoleCount
    extra = 1
    fields = ("name",)
    verbose_name = "Отверстия"
    verbose_name_plural = "Отверстия"


@admin.register(MaterialGroup)
class MaterialGroupAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    form = MaterialGroupAdminForm
    change_list_template = "admin/core/materialgroup/change_list.html"
    change_form_template = "admin/core/materialgroup/change_form.html"
    list_display = ("name", "materials_count", "flag_chips", "types_preview")
    list_display_links = ("name",)
    list_filter = ()
    search_fields = ("name", "description")
    inlines = [
        MaterialGroupTypeInline,
        MaterialGroupBrandInline,
        MaterialGroupColorInline,
        MaterialGroupGritInline,
        MaterialGroupDiameterInline,
        MaterialGroupHoleCountInline,
    ]
    fieldsets = (
        (None, {"fields": ("name",)}),
        (
            "Поля в карточке материала",
            {
                "classes": ("material-group-flags",),
                "description": "Включённые поля появятся в карточке материала и в списке.",
                "fields": (
                    "has_grade",
                    "has_sheet_size",
                    "has_brand",
                    "has_color",
                    "has_grit",
                    "has_diameter",
                    "has_hole_count",
                ),
            },
        ),
        (
            "Описание",
            {
                "classes": ("collapse",),
                "fields": ("description",),
            },
        ),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(_materials_count=Count("materials"))
            .prefetch_related("type_choices")
        )

    def get_search_results(self, request, queryset, search_term):
        term = (search_term or "").strip()
        if not term:
            return queryset.order_by("name"), False
        needle = term.casefold().replace("ё", "е")
        matched_ids = [
            group.pk
            for group in queryset
            if needle in (group.name or "").casefold().replace("ё", "е")
        ]
        return queryset.filter(pk__in=matched_ids).order_by("name"), False

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        if obj is not None:
            context["materials_of_group_count"] = obj.materials.count()
            context["materials_of_group_url"] = (
                reverse("admin:core_material_changelist") + f"?group={obj.pk}"
            )
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url, obj=obj
        )

    @admin.display(description="Карт.")
    def materials_count(self, obj):
        count = getattr(obj, "_materials_count", None)
        if count is None:
            count = obj.materials.count() if obj and obj.pk else 0
        return format_html('<span class="mg-card-count">{} карт.</span>', count)

    @admin.display(description="Поля")
    def flag_chips(self, obj):
        labels = material_group_flag_chips(obj)
        if not labels:
            return mark_safe('<span class="mg-card-empty"></span>')
        return format_html(
            '<ul class="mg-card-flags">{}</ul>',
            format_html_join("", "<li>{}</li>", ((label,) for label in labels)),
        )

    @admin.display(description="Типы")
    def types_preview(self, obj):
        names = [
            (choice.name or "").strip()
            for choice in obj.type_choices.all()
            if (choice.name or "").strip()
        ]
        if not names:
            return mark_safe('<span class="mg-card-empty"></span>')
        return format_html('<div class="mg-card-types">{}</div>', " · ".join(names))


class MaterialMultiListFilter(admin.SimpleListFilter):
    """Несколько значений одного фильтра: ?group=1,6&brand=Tury,Flexione."""

    template = "admin/core/material/multi_filter.html"

    def value_list(self):
        raw = self.value()
        if not raw:
            return []
        return [part for part in str(raw).split(",") if part.strip()]

    def queryset(self, request, queryset):
        values = self.value_list()
        if not values:
            return queryset
        return self.filter_queryset(queryset, values)

    def filter_queryset(self, queryset, values):
        raise NotImplementedError

    def choices(self, changelist):
        selected = set(self.value_list())
        for lookup, title in self.lookup_choices:
            key = str(lookup)
            yield {
                "selected": key in selected,
                "display": title,
                "value": key,
            }


class MaterialGroupMultiFilter(MaterialMultiListFilter):
    title = "Группа"
    parameter_name = "group"

    def lookups(self, request, model_admin):
        return list(
            MaterialGroup.objects.filter(materials__isnull=False)
            .distinct()
            .order_by("name")
            .values_list("pk", "name")
        )

    def filter_queryset(self, queryset, values):
        ids = []
        for raw in values:
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        if not ids:
            return queryset
        return queryset.filter(group_id__in=ids)


class MaterialCharMultiFilter(MaterialMultiListFilter):
    field_name = ""

    def lookups(self, request, model_admin):
        if not self.field_name:
            return []
        empty = {self.field_name: ""}
        values = (
            Material.objects.exclude(**empty)
            .exclude(**{self.field_name: None})
            .order_by(self.field_name)
            .values_list(self.field_name, flat=True)
            .distinct()
        )
        return [(value, value) for value in values if str(value).strip()]

    def filter_queryset(self, queryset, values):
        return queryset.filter(**{f"{self.field_name}__in": values})


class MaterialTypeMultiFilter(MaterialCharMultiFilter):
    title = "Тип"
    parameter_name = "material_type"
    field_name = "material_type"


class MaterialBrandMultiFilter(MaterialCharMultiFilter):
    title = "Бренд"
    parameter_name = "brand"
    field_name = "brand"


class MaterialColorMultiFilter(MaterialCharMultiFilter):
    title = "Цвет"
    parameter_name = "color"
    field_name = "color"


class MaterialGritMultiFilter(MaterialCharMultiFilter):
    title = "Зерно"
    parameter_name = "grit"
    field_name = "grit"


@admin.register(Material)
class MaterialAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    form = MaterialAdminForm
    change_form_template = "admin/core/material/change_form.html"
    change_list_template = "admin/core/material/change_list.html"
    list_display = (
        "photo_thumb",
        "name",
        "group",
        "group_params",
        "unit",
        "current_stock",
    )
    list_filter = (
        MaterialGroupMultiFilter,
        MaterialTypeMultiFilter,
        MaterialBrandMultiFilter,
        MaterialColorMultiFilter,
        MaterialGritMultiFilter,
    )
    search_fields = (
        "name",
        "material_type",
        "brand",
        "color",
        "grit",
        "diameter_mm",
        "hole_count",
        "grade",
        "unit",
        "group__name",
    )
    actions = [copy_materials]
    autocomplete_fields = ("group",)
    readonly_fields = ("sheet_geometry_preview",)
    fieldsets = (
        (
            None,
            {
                "classes": ("material-card-compact",),
                "fields": (
                    "photo",
                    "name",
                    "group",
                    "material_type",
                    "brand",
                    "color",
                    "grit",
                    "diameter_mm",
                    "hole_count",
                    "grade",
                    "unit",
                    "purchase_price",
                    ("sheet_length_mm", "sheet_width_mm", "thickness_mm"),
                    "sheet_geometry_preview",
                ),
            },
        ),
    )

    @admin.display(description="Пл., м²")
    def area_m2_display(self, obj):
        if not obj or obj.area_m2 is None:
            return "—"
        return format(obj.area_m2.quantize(Decimal("0.0001")), "f")

    @admin.display(description="Расчёт площади")
    def sheet_geometry_preview(self, obj):
        return mark_safe(
            '<div id="material-sheet-area-preview" class="material-sheet-area-preview">'
            "Задайте длину и ширину листа</div>"
        )

    @staticmethod
    def _normalize_material_search_text(value) -> str:
        return str(value or "").casefold().replace("ё", "е")

    @classmethod
    def _material_search_haystack(cls, material) -> str:
        return cls._normalize_material_search_text(
            " ".join(
                str(part or "")
                for part in (
                    material.name,
                    material.material_type,
                    material.brand,
                    material.color,
                    material.grit,
                    material.diameter_mm,
                    material.hole_count,
                    material.grade,
                    material.unit,
                    material.group.name if material.group_id else "",
                    material.thickness_mm,
                )
            )
        )

    def get_search_results(self, request, queryset, search_term):
        term = (search_term or "").strip()
        if term:
            tokens = [
                self._normalize_material_search_text(token)
                for token in re.split(r"\s+", term)
                if token.strip()
            ]
            if tokens:
                rows = list(queryset.select_related("group").order_by("name"))
                matched_ids = [
                    material.pk
                    for material in rows
                    if all(token in self._material_search_haystack(material) for token in tokens)
                ]
                return queryset.model.objects.filter(pk__in=matched_ids).select_related("group").order_by("name"), False
        return super().get_search_results(request, queryset, search_term)

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("group")
        # Автодополнение в техкарте: пустой поиск отдаёт первую страницу (20 шт.) — порядок по имени,
        # чтобы подгружаемые страницы и полнотекстовый поиск были предсказуемы.
        if "/autocomplete/" in request.path:
            return qs.order_by("name")
        return qs

    @admin.display(description="Параметры")
    def group_params(self, obj):
        items = material_card_group_params(obj)
        if not items:
            return "—"
        return format_html(
            '<ul class="laser-material-card-params">{}</ul>',
            format_html_join(
                "",
                '<li><span class="k">{}</span> <span class="v">{}</span></li>',
                items,
            ),
        )

    def get_urls(self):
        info = self.model._meta.app_label, self.model._meta.model_name
        custom = [
            path(
                "tc-meta/<int:object_id>/",
                self.admin_site.admin_view(self.techcard_inline_meta_json),
                name="%s_%s_techcard_inline_meta" % info,
            ),
            path(
                "group-meta/",
                self.admin_site.admin_view(self.group_meta_json),
                name="%s_%s_group_meta" % info,
            ),
            path(
                "group-choice-add/",
                self.admin_site.admin_view(self.group_choice_add_json),
                name="%s_%s_group_choice_add" % info,
            ),
        ]
        return custom + super().get_urls()

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        formfield = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name == "group" and formfield is not None:
            formfield.widget.attrs["data-ajax--delay"] = "0"
            formfield.widget.attrs["data-minimum-input-length"] = "0"
            wrapper = formfield.widget
            if hasattr(wrapper, "can_view_related"):
                wrapper.can_view_related = False
            if hasattr(wrapper, "can_delete_related"):
                wrapper.can_delete_related = False
        return formfield

    def group_meta_json(self, request):
        """Типы, ед., сорт, бренд и цвет для выбранной группы материалов."""
        if not request.user.is_staff:
            return JsonResponse({"error": "forbidden"}, status=403)
        raw = (request.GET.get("group_id") or "").strip()
        if not raw:
            return JsonResponse(_material_group_meta_payload())
        try:
            group_id = int(raw)
        except (TypeError, ValueError):
            return JsonResponse(_material_group_meta_payload())
        try:
            group = MaterialGroup.objects.prefetch_related(
                "type_choices",
                "brand_choices",
                "color_choices",
            ).get(pk=group_id)
        except MaterialGroup.DoesNotExist:
            return JsonResponse(_material_group_meta_payload())
        return JsonResponse(_material_group_meta_payload(group))

    def group_choice_add_json(self, request):
        """Добавить или переименовать тип/бренд/цвет в списке группы."""
        if request.method != "POST":
            return JsonResponse({"error": "method"}, status=405)
        if not request.user.is_staff:
            return JsonResponse({"error": "forbidden"}, status=403)
        if not (
            request.user.has_perm("core.change_material")
            or request.user.has_perm("core.change_materialgroup")
        ):
            return JsonResponse({"error": "forbidden"}, status=403)
        kind = (request.POST.get("kind") or "").strip()
        name = (request.POST.get("name") or "").strip()
        old_name = (request.POST.get("old_name") or "").strip()
        action = (request.POST.get("action") or "add").strip()
        raw = (request.POST.get("group_id") or "").strip()
        if kind not in _GROUP_CHOICE_MODELS:
            return JsonResponse({"error": "kind"}, status=400)
        if not name:
            return JsonResponse({"error": "name"}, status=400)
        try:
            group_id = int(raw)
        except (TypeError, ValueError):
            return JsonResponse({"error": "group"}, status=400)
        try:
            group = MaterialGroup.objects.get(pk=group_id)
        except MaterialGroup.DoesNotExist:
            return JsonResponse({"error": "group"}, status=404)
        if action == "rename" and old_name:
            saved = _rename_material_group_choice(group, kind, old_name, name)
        else:
            saved = _ensure_material_group_choice(group, kind, name)
        group.refresh_from_db()
        payload = _material_group_meta_payload(group)
        payload["name"] = saved
        payload["kind"] = kind
        return JsonResponse(payload)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        group = obj.group
        if group is None:
            return
        if obj.material_type:
            _ensure_material_group_choice(group, "type", obj.material_type)
        if obj.brand:
            _ensure_material_group_choice(group, "brand", obj.brand)
        if obj.color:
            _ensure_material_group_choice(group, "color", obj.color)

    def techcard_inline_meta_json(self, request, object_id):
        """Ед. изм. и габариты листа для зеркала «Норма» в инлайне позиций техкарты."""
        if not request.user.is_staff:
            return JsonResponse({"error": "forbidden"}, status=403)
        try:
            m = Material.objects.only(
                "unit",
                "sheet_length_mm",
                "sheet_width_mm",
                "thickness_mm",
                "area_m2",
            ).get(pk=object_id)
        except Material.DoesNotExist:
            return JsonResponse({"error": "not found"}, status=404)
        return JsonResponse(
            {
                "unit": (m.unit or "").strip(),
                "sheet_length_mm": "" if m.sheet_length_mm is None else format(m.sheet_length_mm, "f"),
                "sheet_width_mm": "" if m.sheet_width_mm is None else format(m.sheet_width_mm, "f"),
                "thickness_mm": "" if m.thickness_mm is None else format(m.thickness_mm, "f"),
                "area_m2": "" if m.area_m2 is None else format(m.area_m2, "f"),
            }
        )

    @admin.display(description="Фото")
    def photo_thumb(self, obj):
        if not obj or not obj.photo:
            return "—"
        try:
            url = obj.photo.url
        except (ValueError, OSError):
            return "—"
        return format_html(
            '<img src="{}" width="72" height="72" alt="" />',
            url,
        )


@admin.register(MaterialBatch)
class MaterialBatchAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = ("material", "movement_type", "quantity", "unit_price", "date")
    list_filter = ("movement_type", "material")
    search_fields = ("material__name",)


@admin.register(Organization)
class OrganizationAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = ("name", "inn", "kpp", "ogrn", "is_individual", "is_supplier", "is_buyer")
    list_filter = ("is_individual", "is_supplier", "is_buyer")
    search_fields = ("name", "inn", "ogrn")
    readonly_fields = ("fns_status", "fns_updated_at", "fns_data_pretty")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "inn",
                    "kpp",
                    "ogrn",
                    "legal_address",
                    "phone",
                    "email",
                    "is_individual",
                ),
            },
        ),
        (
            "Подписант",
            {
                "fields": ("general_director", "signer_name", "signer_position", "signer_authority"),
            },
        ),
        (
            "Банковские реквизиты",
            {
                "fields": ("bank_account", "bank_name", "bank_bik", "bank_corr_account"),
            },
        ),
        (
            "Данные ФНС",
            {
                "fields": ("fns_status", "fns_updated_at", "fns_data_pretty"),
                "classes": ("collapse",),
                "description": "Полный ответ ФНС хранится в raw-виде для просмотра всех доступных полей.",
            },
        ),
        (
            "Роли",
            {
                "fields": ("is_supplier", "is_buyer"),
                "description": "Контрагент может быть поставщиком, покупателем или тем и другим.",
            },
        ),
    )
    change_form_template = "admin/core/organization/change_form.html"
    change_list_template = "admin/core/organization/changelist.html"

    def get_search_results(self, request, queryset, search_term):
        """Автодополнение поля supplier (товар, закупки) — только с ролью «Поставщик»."""
        qs, use_distinct = super().get_search_results(request, queryset, search_term)
        if request.GET.get("field_name") == "supplier":
            qs = qs.filter(is_supplier=True)
        return qs, use_distinct

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["fns_search_url"] = reverse("admin:fns_search_inn")
        return super().changelist_view(request, extra_context=extra_context)

    def get_changeform_initial_data(self, request):
        """Подстановка реквизитов из поиска ФНС (ссылка «Создать контрагента» с GET-параметрами)."""
        initial = super().get_changeform_initial_data(request)
        if request.method == "GET" and not request.GET.get("_popup"):
            for key in ("name", "inn", "kpp", "ogrn", "legal_address"):
                if request.GET.get(key) is not None:
                    initial[key] = request.GET.get(key)
            if request.GET.get("is_individual") is not None:
                initial["is_individual"] = request.GET.get("is_individual") in ("1", "true", "yes")
        return initial

    @staticmethod
    def _normalized_digits(value: str) -> str:
        return re.sub(r"\D", "", str(value or ""))

    @staticmethod
    def _normalized_text(value: str) -> str:
        return str(value or "").strip()

    @staticmethod
    def _parse_bool(value) -> bool:
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _normalize_email_or_empty(value: str) -> str:
        email = str(value or "").strip()
        if not email:
            return ""
        try:
            validate_email(email)
        except ValidationError:
            return ""
        return email

    @classmethod
    def _extract_fns_general_director(cls, payload) -> str:
        raw = payload.get("raw") if isinstance(payload, dict) else {}
        if not isinstance(raw, dict):
            return ""

        def _extract_fio(candidate) -> str:
            if not isinstance(candidate, dict):
                return ""
            fio = cls._normalized_text(
                candidate.get("ФИОПолн")
                or candidate.get("ФИОРуководителя")
                or candidate.get("ФИО")
                or candidate.get("НаимПолн")
                or candidate.get("Наим")
            )
            return fio if len(fio) >= 5 else ""

        # 1) Частый формат API egr: верхнеуровневый блок "Руководитель"
        fio = _extract_fio(raw.get("Руководитель"))
        if fio:
            return fio

        # 2) Запасной обход вложенности для разных форматов
        stack = [raw]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key, value in node.items():
                    if "руковод" in str(key).lower():
                        fio = _extract_fio(value)
                        if fio:
                            return fio
                    if isinstance(value, (dict, list)):
                        stack.append(value)
            elif isinstance(node, list):
                for item in node:
                    if isinstance(item, (dict, list)):
                        stack.append(item)
        return ""

    @classmethod
    def _extract_fns_contact_value(cls, payload, key_candidates) -> str:
        raw = payload.get("raw") if isinstance(payload, dict) else {}
        if not isinstance(raw, dict):
            return ""
        contacts = raw.get("Контакты")
        if not isinstance(contacts, dict):
            return ""
        for key in key_candidates:
            value = contacts.get(key)
            if isinstance(value, list):
                for item in value:
                    text = cls._normalized_text(item)
                    if text:
                        return text
            text = cls._normalized_text(value)
            if text:
                return text
        return ""

    @admin.display(description="ФНС: полный набор полей")
    def fns_data_pretty(self, obj):
        if not obj or not obj.fns_raw_data:
            return "—"
        text = json.dumps(obj.fns_raw_data, ensure_ascii=False, indent=2)
        return format_html(
            '<pre style="max-height:320px;overflow:auto;white-space:pre-wrap;margin:0">{}</pre>',
            text,
        )

    def _find_existing_from_payload(self, payload):
        inn_digits = self._normalized_digits(payload.get("inn"))
        ogrn_digits = self._normalized_digits(payload.get("ogrn"))
        if not inn_digits and not ogrn_digits:
            return None

        for org in Organization.objects.all().only("pk", "inn", "ogrn"):
            same_inn = bool(inn_digits and self._normalized_digits(org.inn) == inn_digits)
            same_ogrn = bool(ogrn_digits and self._normalized_digits(org.ogrn) == ogrn_digits)
            if same_inn or same_ogrn:
                return org
        return None

    def _update_missing_fields_from_fns_payload(self, org, payload, overwrite_mismatched: bool = False):
        updated_fields = []
        mismatched_fields = []

        incoming_map = {
            "name": self._normalized_text(payload.get("name")),
            "kpp": self._normalized_text(payload.get("kpp")),
            "ogrn": self._normalized_text(payload.get("ogrn")),
            "legal_address": self._normalized_text(payload.get("legal_address")),
            "general_director": self._extract_fns_general_director(payload),
            "phone": self._extract_fns_contact_value(payload, ("Телефоны", "Телефон", "Phone")),
            "email": self._normalize_email_or_empty(
                self._extract_fns_contact_value(payload, ("E-mail", "Email", "Почта"))
            ),
        }

        for field_name, incoming_value in incoming_map.items():
            if not incoming_value:
                continue
            current_value = self._normalized_text(getattr(org, field_name))
            if not current_value:
                setattr(org, field_name, incoming_value)
                updated_fields.append(field_name)
            elif current_value != incoming_value:
                mismatched_fields.append(field_name)
                if overwrite_mismatched:
                    setattr(org, field_name, incoming_value)
                    updated_fields.append(field_name)

        incoming_is_individual = self._parse_bool(payload.get("is_individual"))
        if incoming_is_individual and not org.is_individual:
            org.is_individual = True
            updated_fields.append("is_individual")
        elif org.is_individual != incoming_is_individual:
            mismatched_fields.append("is_individual")

        if updated_fields:
            org.save(update_fields=updated_fields)
        return updated_fields, mismatched_fields

    def add_view(self, request, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["fns_search_url"] = reverse("admin:fns_search_inn")
        extra_context["bank_bik_lookup_url"] = reverse("admin:bank_lookup_bik")
        if request.method == "POST":
            existing = self._find_existing_from_payload(request.POST)
            if existing:
                updated_fields, mismatched_fields = self._update_missing_fields_from_fns_payload(existing, request.POST)
                if updated_fields:
                    self.message_user(
                        request,
                        "Контрагент уже существует. Пустые поля в существующей карточке заполнены из данных ФНС: "
                        + ", ".join(updated_fields),
                        level=messages.WARNING,
                    )
                else:
                    self.message_user(
                        request,
                        "Контрагент уже существует в базе. Открыта существующая карточка без создания дубля.",
                        level=messages.WARNING,
                    )
                if mismatched_fields:
                    self.message_user(
                        request,
                        "Обнаружены отличия с данными ФНС по полям: " + ", ".join(sorted(set(mismatched_fields))),
                        level=messages.INFO,
                    )
                return HttpResponseRedirect(reverse("admin:core_organization_change", args=[existing.pk]))
        return super().add_view(request, form_url, extra_context=extra_context)

    def response_add(self, request, obj, post_url_continue=None):
        resp = super().response_add(request, obj, post_url_continue)
        if request.GET.get("_popup") or request.POST.get("_popup"):
            return resp
        if request.POST.get("_continue") or request.POST.get("_addanother"):
            return resp
        return HttpResponseRedirect(reverse("admin:core_organization_changelist"))

    def response_change(self, request, obj):
        resp = super().response_change(request, obj)
        if request.GET.get("_popup") or request.POST.get("_popup"):
            return resp
        if request.POST.get("_continue") or request.POST.get("_addanother"):
            return resp
        return HttpResponseRedirect(reverse("admin:core_organization_changelist"))

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["fns_search_url"] = reverse("admin:fns_search_inn")
        extra_context["bank_bik_lookup_url"] = reverse("admin:bank_lookup_bik")
        extra_context["refresh_from_fns_url"] = reverse(
            "admin:organization_refresh_from_fns", args=[object_id]
        )
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "fns-search-inn/",
                self.admin_site.admin_view(self.fns_search_inn_view),
                name="fns_search_inn",
            ),
            path(
                "bank-lookup-bik/",
                self.admin_site.admin_view(self.bank_lookup_bik_view),
                name="bank_lookup_bik",
            ),
            path(
                "<int:object_id>/refresh-from-fns/",
                self.admin_site.admin_view(self.refresh_from_fns_view),
                name="organization_refresh_from_fns",
            ),
        ]
        return custom + urls

    def bank_lookup_bik_view(self, request):
        if request.method != "GET":
            return JsonResponse({"ok": False, "error": "Метод не поддерживается."}, status=405)
        bik = (request.GET.get("bik") or "").strip()
        try:
            data = fetch_bank_details_by_bik(bik)
        except ValueError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            return JsonResponse({"ok": False, "error": f"Ошибка поиска по БИК: {exc}"}, status=500)
        return JsonResponse(
            {
                "ok": True,
                "bank_name": data.get("bank_name") or "",
                "bank_corr_account": data.get("corr_account") or "",
            }
        )

    def refresh_from_fns_view(self, request, object_id: int):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        org = get_object_or_404(Organization, pk=object_id)
        inn = self._normalized_digits(org.inn)
        if not inn:
            messages.error(request, "Нельзя обновить из ФНС: у контрагента не заполнен ИНН.")
            return HttpResponseRedirect(reverse("admin:core_organization_change", args=[org.pk]))

        try:
            results = fetch_contragents(inn)
        except Exception as exc:
            messages.error(request, f"Ошибка запроса в ФНС: {exc}")
            return HttpResponseRedirect(reverse("admin:core_organization_change", args=[org.pk]))

        if not results:
            messages.warning(request, "ФНС не вернула данные по указанному ИНН.")
            return HttpResponseRedirect(reverse("admin:core_organization_change", args=[org.pk]))

        payload = None
        for row in results:
            if self._normalized_digits(row.get("inn")) == inn:
                payload = row
                break
        if payload is None:
            payload = results[0]

        # Метод search не всегда содержит блок "Руководитель",
        # поэтому дополнительно забираем расширенный профиль через egr.
        try:
            egr_raw = fetch_contragent_egr_payload(inn)
        except Exception:
            egr_raw = {}
        if isinstance(egr_raw, dict) and egr_raw:
            payload = {
                **payload,
                "kpp": self._normalized_text(payload.get("kpp") or egr_raw.get("КПП")),
                "ogrn": self._normalized_text(payload.get("ogrn") or egr_raw.get("ОГРН") or egr_raw.get("ОГРНИП")),
                "status": self._normalized_text(payload.get("status") or egr_raw.get("Статус")),
                "legal_address": self._normalized_text(
                    payload.get("legal_address")
                    or egr_raw.get("АдресПолн")
                    or (egr_raw.get("Адрес") or {}).get("АдресПолн")
                ),
                "raw": egr_raw,
            }

        updated_fields, mismatched_fields = self._update_missing_fields_from_fns_payload(
            org,
            payload,
            overwrite_mismatched=True,
        )
        raw_payload = payload.get("raw") if isinstance(payload, dict) else {}
        org.fns_raw_data = raw_payload if isinstance(raw_payload, dict) else {}
        org.fns_status = self._normalized_text(payload.get("status"))
        org.fns_updated_at = timezone.now()
        org.save(update_fields=["fns_raw_data", "fns_status", "fns_updated_at"])
        if updated_fields:
            messages.success(
                request,
                "Данные контрагента обновлены из ФНС: " + ", ".join(sorted(set(updated_fields))),
            )
        else:
            messages.info(request, "Изменений по данным ФНС не обнаружено.")
        if mismatched_fields:
            messages.warning(
                request,
                "Обнаружены отличия, применены данные ФНС по полям: "
                + ", ".join(sorted(set(mismatched_fields))),
            )

        return HttpResponseRedirect(reverse("admin:core_organization_change", args=[org.pk]))

    def fns_search_inn_view(self, request):
        """Поиск контрагентов по ИНН или наименованию в базе ФНС (API api-fns.ru)."""
        from urllib.parse import urlencode
        if request.method not in {"GET", "POST"}:
            return HttpResponseNotAllowed(["GET", "POST"])
        error = None
        results = []
        inn = (request.POST.get("inn") or request.GET.get("inn") or "").strip()
        if request.method == "POST" and inn:
            try:
                results = fetch_contragents(inn)
            except ValueError as e:
                error = str(e)
            except Exception as e:
                error = f"Ошибка при поиске: {e}"
        try:
            add_url = reverse("admin:core_organization_add")
            list_url = reverse("admin:core_organization_changelist")
        except Exception as e:
            return self._fns_search_error_response(request, f"Ошибка формирования ссылок: {e}")
        # Ссылка «Создать контрагента» с GET-параметрами для подстановки в форму
        for r in results:
            q = {
                "name": r["name"],
                "inn": r["inn"],
                "kpp": r["kpp"],
                "ogrn": r["ogrn"],
                "legal_address": r["legal_address"],
                "is_individual": "1" if r["is_individual"] else "0",
            }
            r["create_url"] = f"{add_url}?{urlencode({k: v for k, v in q.items() if v})}"
        try:
            base_context = self.admin_site.each_context(request)
        except Exception as e:
            base_context = {"site_title": "Админка", "site_header": "Laser ERP"}
        context = {
            **base_context,
            "title": "Поиск контрагента по ИНН или наименованию (ФНС)",
            "inn": inn,
            "results": results,
            "error": error,
            "opts": self.model._meta,
            "list_url": list_url,
            "add_url": add_url,
            "is_post": request.method == "POST",
        }
        try:
            return render(
                request,
                "admin/core/organization/fns_search_inn.html",
                context,
            )
        except Exception as e:
            return self._fns_search_error_response(request, str(e))

    def _fns_search_error_response(self, request, message):
        """Ответ с сообщением об ошибке для страницы поиска по ИНН."""
        try:
            list_url = reverse("admin:core_organization_changelist")
            add_url = reverse("admin:core_organization_add")
        except Exception:
            list_url = "/admin/core/organization/"
            add_url = "/admin/core/organization/add/"
        try:
            base_context = self.admin_site.each_context(request)
        except Exception:
            base_context = {}
        context = {
            **base_context,
            "title": "Поиск контрагента по ИНН или наименованию (ФНС)",
            "error": message,
            "list_url": list_url,
            "add_url": add_url,
            "opts": self.model._meta,
            "inn": "",
            "results": [],
            "is_post": False,
        }
        return render(
            request,
            "admin/core/organization/fns_search_inn.html",
            context,
            status=500,
        )


@admin.register(ExpenseLedgerEntry)
class ExpenseLedgerEntryAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    """
    Единый read-only журнал расходов (агрегатор документов закупок).
    """

    change_list_template = "admin/core/expenseledgerentry/change_list.html"
    list_per_page = 100

    DOC_SUPPLIER_INVOICE = "supplier_invoice"
    DOC_GOODS_RECEIPT = "goods_receipt"
    DOC_RECEIVED_VAT_INVOICE = "received_vat_invoice"

    DOC_TYPE_CHOICES = (
        (DOC_SUPPLIER_INVOICE, "Счёт поставщика"),
        (DOC_GOODS_RECEIPT, "Приёмка"),
        (DOC_RECEIVED_VAT_INVOICE, "Счёт-фактура полученный"),
    )

    PRESET_CHOICES = (
        ("approval", "На согласовании"),
        ("to_pay", "К оплате"),
        ("paid", "Оплаченные"),
        ("overdue", "Просрочка"),
    )

    STATUS_LABELS = {
        "draft": "Черновик",
        "approved": "Утверждён",
        "posted": "Проведён",
        "paid": "Оплачен",
        "cancelled": "Отменён",
    }

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return ExpenseLedgerEntry.objects.none()

    @staticmethod
    def _parse_date(raw_value: str):
        raw = (raw_value or "").strip()
        if not raw:
            return None
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _as_amount(value):
        return (value or Decimal("0")).quantize(Decimal("0.01"))

    def _build_qs_url(self, request, **updates):
        data = request.GET.copy()
        for key, value in updates.items():
            if value in (None, ""):
                data.pop(key, None)
            else:
                data[key] = str(value)
        data.pop("p", None)
        q = data.urlencode()
        return f"?{q}" if q else "?"

    def _apply_supplier_invoice_preset(self, qs, preset, today):
        if preset == "approval":
            return qs.filter(status=SupplierInvoice.STATUS_DRAFT)
        if preset == "to_pay":
            return qs.filter(status=SupplierInvoice.STATUS_APPROVED)
        if preset == "paid":
            return qs.filter(status=SupplierInvoice.STATUS_PAID)
        if preset == "overdue":
            return qs.filter(
                status__in=[SupplierInvoice.STATUS_DRAFT, SupplierInvoice.STATUS_APPROVED],
                invoice_date__lt=(today - timedelta(days=14)),
            )
        return qs

    def _apply_goods_receipt_preset(self, qs, preset):
        if preset == "approval":
            return qs.filter(status=GoodsReceipt.STATUS_DRAFT)
        if preset == "to_pay":
            return qs.filter(status=GoodsReceipt.STATUS_POSTED)
        if preset == "paid":
            return qs.filter(total_amount__gt=0, paid_amount__gte=F("total_amount"))
        if preset == "overdue":
            return qs.none()
        return qs

    def _apply_received_vat_preset(self, qs, preset, today):
        if preset == "approval":
            return qs.filter(status="draft")
        if preset == "to_pay":
            return qs.none()
        if preset == "paid":
            return qs.none()
        if preset == "overdue":
            return qs.filter(status="draft", invoice_date__lt=(today - timedelta(days=14)))
        return qs

    def _collect_rows(self, request):
        doc_type = (request.GET.get("doc_type") or "").strip()
        status = (request.GET.get("status") or "").strip()
        category = (request.GET.get("category") or "").strip()
        supplier_id = (request.GET.get("supplier_id") or "").strip()
        our_organization_id = (request.GET.get("our_organization_id") or "").strip()
        search_q = (request.GET.get("q") or "").strip()
        preset = (request.GET.get("preset") or "").strip()

        date_from = self._parse_date(request.GET.get("date_from"))
        date_to = self._parse_date(request.GET.get("date_to"))
        today = timezone.localdate()

        rows = []
        if doc_type in ("", self.DOC_SUPPLIER_INVOICE):
            qs = SupplierInvoice.objects.select_related("supplier", "our_organization")
            if date_from:
                qs = qs.filter(invoice_date__gte=date_from)
            if date_to:
                qs = qs.filter(invoice_date__lte=date_to)
            if supplier_id:
                qs = qs.filter(supplier_id=supplier_id)
            if our_organization_id:
                qs = qs.filter(our_organization_id=our_organization_id)
            if status:
                qs = qs.filter(status=status)
            if category:
                qs = qs.filter(expense_category=category)
            if search_q:
                qs = qs.filter(
                    Q(number__icontains=search_q)
                    | Q(comment__icontains=search_q)
                    | Q(supplier__name__icontains=search_q)
                )
            qs = self._apply_supplier_invoice_preset(qs, preset, today)
            for obj in qs:
                rows.append(
                    {
                        "date": obj.invoice_date,
                        "doc_type": self.DOC_SUPPLIER_INVOICE,
                        "doc_type_label": "Счёт поставщика",
                        "number": obj.number or f"СП-{obj.pk}",
                        "supplier_name": obj.supplier.name if obj.supplier_id else "—",
                        "our_organization_name": obj.our_organization.name if obj.our_organization_id else "—",
                        "amount": self._as_amount(obj.total_amount),
                        "expense_category": obj.get_expense_category_display() if obj.expense_category else "—",
                        "status": obj.status,
                        "status_label": obj.get_status_display(),
                        "comment": obj.comment or "",
                        "open_url": reverse("admin:procurement_supplierinvoice_change", args=[obj.pk]),
                    }
                )

        if doc_type in ("", self.DOC_GOODS_RECEIPT):
            qs = GoodsReceipt.objects.select_related("supplier", "our_organization")
            if date_from:
                qs = qs.filter(received_at__date__gte=date_from)
            if date_to:
                qs = qs.filter(received_at__date__lte=date_to)
            if supplier_id:
                qs = qs.filter(supplier_id=supplier_id)
            if our_organization_id:
                qs = qs.filter(our_organization_id=our_organization_id)
            if status:
                qs = qs.filter(status=status)
            if search_q:
                qs = qs.filter(
                    Q(number__icontains=search_q)
                    | Q(incoming_number__icontains=search_q)
                    | Q(comment__icontains=search_q)
                    | Q(supplier__name__icontains=search_q)
                )
            qs = self._apply_goods_receipt_preset(qs, preset)
            for obj in qs:
                rows.append(
                    {
                        "date": timezone.localdate(obj.received_at) if obj.received_at else None,
                        "doc_type": self.DOC_GOODS_RECEIPT,
                        "doc_type_label": "Приёмка",
                        "number": obj.number or f"ПРИ-{obj.pk}",
                        "supplier_name": obj.supplier.name if obj.supplier_id else "—",
                        "our_organization_name": obj.our_organization.name if obj.our_organization_id else "—",
                        "amount": self._as_amount(obj.total_amount),
                        "expense_category": "Материалы/товары",
                        "status": obj.status,
                        "status_label": obj.get_status_display(),
                        "comment": obj.comment or "",
                        "open_url": reverse("admin:procurement_goodsreceipt_change", args=[obj.pk]),
                    }
                )

        if doc_type in ("", self.DOC_RECEIVED_VAT_INVOICE):
            qs = ReceivedVatInvoice.objects.select_related("supplier", "our_organization")
            if date_from:
                qs = qs.filter(invoice_date__gte=date_from)
            if date_to:
                qs = qs.filter(invoice_date__lte=date_to)
            if supplier_id:
                qs = qs.filter(supplier_id=supplier_id)
            if our_organization_id:
                qs = qs.filter(our_organization_id=our_organization_id)
            if status:
                qs = qs.filter(status=status)
            if search_q:
                qs = qs.filter(
                    Q(number__icontains=search_q)
                    | Q(comment__icontains=search_q)
                    | Q(supplier__name__icontains=search_q)
                )
            qs = self._apply_received_vat_preset(qs, preset, today)
            for obj in qs:
                rows.append(
                    {
                        "date": obj.invoice_date,
                        "doc_type": self.DOC_RECEIVED_VAT_INVOICE,
                        "doc_type_label": "Счёт-фактура полученный",
                        "number": obj.number or f"СФ-{obj.pk}",
                        "supplier_name": obj.supplier.name if obj.supplier_id else "—",
                        "our_organization_name": obj.our_organization.name if obj.our_organization_id else "—",
                        "amount": self._as_amount(obj.total_amount),
                        "expense_category": "НДС",
                        "status": obj.status,
                        "status_label": self.STATUS_LABELS.get(obj.status, obj.status or "—"),
                        "comment": obj.comment or "",
                        "open_url": reverse("admin:procurement_receivedvatinvoice_change", args=[obj.pk]),
                    }
                )

        rows.sort(key=lambda row: (row.get("date") or datetime.min.date(), row.get("number") or ""), reverse=True)
        total_amount = sum((row["amount"] for row in rows), Decimal("0")).quantize(Decimal("0.01"))
        return rows, total_amount

    def changelist_view(self, request, extra_context=None):
        rows, total_amount = self._collect_rows(request)
        suppliers = Organization.objects.filter(is_supplier=True).order_by("name")
        our_organizations = Organization.objects.filter(is_buyer=True).order_by("name")
        status_choices = [
            ("draft", "Черновик"),
            ("approved", "Утверждён"),
            ("posted", "Проведён"),
            ("paid", "Оплачен"),
            ("cancelled", "Отменён"),
        ]

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Расходы",
            "rows": rows,
            "total_amount": total_amount,
            "rows_count": len(rows),
            "doc_type_choices": self.DOC_TYPE_CHOICES,
            "category_choices": SupplierInvoice.EXPENSE_CATEGORY_CHOICES,
            "preset_choices": self.PRESET_CHOICES,
            "status_choices": status_choices,
            "suppliers": suppliers,
            "our_organizations": our_organizations,
            "filter_values": {
                "date_from": (request.GET.get("date_from") or "").strip(),
                "date_to": (request.GET.get("date_to") or "").strip(),
                "doc_type": (request.GET.get("doc_type") or "").strip(),
                "status": (request.GET.get("status") or "").strip(),
                "category": (request.GET.get("category") or "").strip(),
                "supplier_id": (request.GET.get("supplier_id") or "").strip(),
                "our_organization_id": (request.GET.get("our_organization_id") or "").strip(),
                "q": (request.GET.get("q") or "").strip(),
                "preset": (request.GET.get("preset") or "").strip(),
            },
            "clear_filters_url": self._build_qs_url(request, date_from="", date_to="", doc_type="", status="", category="", supplier_id="", our_organization_id="", q="", preset=""),
            "preset_links": [
                {
                    "code": code,
                    "label": label,
                    "url": self._build_qs_url(request, preset=code),
                    "is_active": (request.GET.get("preset") or "").strip() == code,
                }
                for code, label in self.PRESET_CHOICES
            ],
        }
        context.update(extra_context or {})
        return render(request, self.change_list_template, context)


@admin.register(Warehouse)
class WarehouseAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = ("name", "organization")
    list_filter = ("organization",)
    search_fields = ("name",)
    autocomplete_fields = ("organization",)


@admin.register(MaterialStock)
class MaterialStockAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = ("material", "quantity", "material_type_display", "warehouse", "material_card_link")
    list_filter = ("warehouse",)
    search_fields = ("material__name", "material__material_type")
    autocomplete_fields = ("warehouse", "material")

    @admin.display(description="Тип")
    def material_type_display(self, obj):
        return obj.material.material_type or "—" if obj and obj.material_id else "—"

    @admin.display(description="Карточка")
    def material_card_link(self, obj):
        if not obj or not obj.material_id:
            return "—"
        try:
            url = reverse("admin:core_material_change", args=[obj.material_id])
        except NoReverseMatch:
            return "—"
        return format_html('<a href="{}">Размеры / правка</a>', url)


@admin.register(ProductStock)
class ProductStockAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = (
        "warehouse",
        "product",
        "quantity",
        "col_production_pending",
        "col_effective_quantity",
    )
    list_filter = ("warehouse",)
    search_fields = ("product__name",)
    autocomplete_fields = ("warehouse", "product")

    def get_queryset(self, request):
        dec3 = DecimalField(max_digits=16, decimal_places=3)
        return (
            super()
            .get_queryset(request)
            .annotate(
                _prod_pending=Coalesce(
                    pending_production_quantity_subquery(
                        product_lookup="product_id",
                        warehouse_lookup="warehouse_id",
                    ),
                    Value(Decimal("0")),
                    output_field=dec3,
                ),
            )
            .annotate(
                _effective_qty=F("quantity") + F("_prod_pending"),
            )
        )

    @admin.display(description="Ожидание (производство)", ordering="_prod_pending")
    def col_production_pending(self, obj):
        v = getattr(obj, "_prod_pending", None)
        if v is None or v == 0:
            return "—"
        return str(v.quantize(Decimal("0.001")) if isinstance(v, Decimal) else v)

    @admin.display(description="С учётом производства", ordering="_effective_qty")
    def col_effective_quantity(self, obj):
        v = getattr(obj, "_effective_qty", None)
        if v is None:
            return "—"
        return str(v.quantize(Decimal("0.001")) if isinstance(v, Decimal) else v)


class ProductMaterialInline(admin.TabularInline):
    model = ProductMaterial
    extra = 1
    classes = ["compact-inline", "product-extra-inline", "product-extra-inline--materials"]


class ProductLaborInline(admin.TabularInline):
    model = ProductLabor
    extra = 1
    classes = ["compact-inline", "product-extra-inline", "product-extra-inline--labor"]


class ProductAnalogInline(admin.TabularInline):
    model = ProductAnalog
    fk_name = "product"
    extra = 0
    autocomplete_fields = ("analog_product",)
    verbose_name = "Аналог"
    verbose_name_plural = "Аналоги (не более 10)"
    classes = ["compact-inline", "product-extra-inline", "product-extra-inline--analog"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.order_by("order")


class ProductModificationInline(admin.TabularInline):
    class ProductModificationInlineForm(forms.ModelForm):
        class Meta:
            model = ProductModification
            fields = "__all__"
            labels = {
                "sort_order": "↕",
                "thickness_mm": "📏 мм",
                "grade": "🏷 сорт",
                "sanding_sides": "🧽 шл",
                "abrasive_grit": "🔢 P",
                "quantity_factor": "× k",
                "planned_markup_percent": "📈 %",
                "planned_price": "💵 цена",
                "is_active": "🟢 on",
            }

    model = ProductModification
    form = ProductModificationInlineForm
    fk_name = "product"
    extra = 0
    fields = (
        "name_display",
        "thickness_display",
        "grade_display",
        "sanding_display",
        "abrasive_display",
        "planned_price",
        "is_active",
    )
    readonly_fields = (
        "name_display",
        "thickness_display",
        "grade_display",
        "sanding_display",
        "abrasive_display",
    )
    verbose_name = "Модификация"
    verbose_name_plural = "Модификации"
    classes = ["compact-inline", "product-extra-inline", "product-extra-inline--modifications"]

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        # В табличных модификациях убираем help_text, чтобы не дублировать
        # иконки подсказок в каждой ячейке (достаточно верхнего уровня).
        for field in formset.form.base_fields.values():
            field.help_text = ""
        return formset

    @admin.display(description="Себест. (план)")
    def planned_cost_display(self, obj):
        if not obj or not getattr(obj, "pk", None):
            return "—"
        return format(obj.planned_cost, ".2f")

    @admin.display(description="Название")
    def name_display(self, obj):
        if not obj or not getattr(obj, "pk", None):
            return "—"
        return obj.name or "—"

    @admin.display(description="📏 мм")
    def thickness_display(self, obj):
        if not obj or not getattr(obj, "pk", None):
            return "—"
        return str(obj.thickness_mm or "—")

    @admin.display(description="🏷 сорт")
    def grade_display(self, obj):
        if not obj or not getattr(obj, "pk", None):
            return "—"
        return obj.grade or "—"

    @admin.display(description="🧽 шл")
    def sanding_display(self, obj):
        if not obj or not getattr(obj, "pk", None):
            return "—"
        return obj.sanding_sides or "—"

    @admin.display(description="🔢 P")
    def abrasive_display(self, obj):
        if not obj or not getattr(obj, "pk", None):
            return "—"
        return obj.abrasive_grit or "—"

    @admin.display(description="Цена продажи")
    def sale_price_display(self, obj):
        if not obj or not getattr(obj, "pk", None):
            return "—"
        return format(obj.sale_price, ".2f")


class ProductBarcodeInline(admin.TabularInline):
    model = ProductBarcode
    extra = 1
    fk_name = "product"
    fields = ("barcode_type", "value", "comment")
    verbose_name = "Штрихкод"
    verbose_name_plural = "Штрихкоды товара"
    classes = ["compact-inline", "product-extra-inline", "product-extra-inline--barcode"]


class ProductGalleryImageInline(admin.TabularInline):
    model = ProductGalleryImage
    extra = 0
    max_num = 15
    fk_name = "product"
    fields = ("image", "sort_order")
    verbose_name = "Фото"
    verbose_name_plural = "Галерея"
    classes = ["compact-inline", "product-gallery-inline"]


_PRODUCT_UOM_FIELDSET_DESCRIPTION = mark_safe(
    '<p class="product-uom-desc-lead">'
    "Длина, ширина, толщина в мм — только целые (дробь округляется при сохранении). "
    "Пл. и объём считаются по единице измерения."
    "</p>"
    '<details class="product-uom-desc-details">'
    "<summary>Подробно про расчёты</summary>"
    '<div class="product-uom-desc-body">'
    "<p>Ед. шт: длина в мм × ширина в мм → пл. в мм², см², м²; «Длина в м» = длина в мм ÷ 1000; "
    "при толщине — объём м³ = Д×Ш×Т.</p>"
    "<p>Ед. м²: пл. в м² вручную и толщина в мм → мм², см² и объём.</p>"
    "<p>Ед. п.м / м: длина в м вручную, ширина и толщина сечения в мм → объём.</p>"
    "<p>Если для расчёта объёма не хватает данных, ранее введённый объём не затирается.</p>"
    "</div></details>"
)

_PRODUCT_MAIN_FIELDSET_GROUP_HEADING = mark_safe(
    '<p class="help product-group-block-heading" id="product-group-block-heading" '
    'style="margin:0 0 0.65rem;font-weight:600;color:var(--body-quiet-color,#64748b);"></p>'
)


class WarehouseNavFlagFilter(admin.SimpleListFilter):
    """Флаг меню «Склады» в URL (?wh=1). Не фильтрует записи и скрыт в сайдбаре."""

    title = "nav"
    parameter_name = "wh"

    def lookups(self, request, model_admin):
        return (("1", "1"),)

    def queryset(self, request, queryset):
        return queryset

    def has_output(self):
        return False


class ProductKindNavFilter(admin.SimpleListFilter):
    """Сохраняет ?product_kind= в карточном списке ГП, в модалке не показывается."""

    title = "kind"
    parameter_name = "product_kind"

    def lookups(self, request, model_admin):
        return ((Product.PRODUCT_KIND_GOODS, Product.PRODUCT_KIND_GOODS),)

    def queryset(self, request, queryset):
        return queryset

    def has_output(self):
        return False


class ProductGroupMultiFilter(MaterialMultiListFilter):
    title = "Группа"
    parameter_name = "product_group"

    def lookups(self, request, model_admin):
        return list(
            ProductGroup.objects.filter(products__product_kind=Product.PRODUCT_KIND_GOODS)
            .distinct()
            .order_by("name")
            .values_list("pk", "name")
        )

    def filter_queryset(self, queryset, values):
        ids = []
        for raw in values:
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        if not ids:
            return queryset
        return queryset.filter(product_group_id__in=ids)


class ProductThicknessMultiFilter(MaterialMultiListFilter):
    title = "Толщина"
    parameter_name = "sheet_thickness_mm"

    def lookups(self, request, model_admin):
        values = (
            Product.objects.filter(product_kind=Product.PRODUCT_KIND_GOODS)
            .exclude(sheet_thickness_mm=None)
            .order_by("sheet_thickness_mm")
            .values_list("sheet_thickness_mm", flat=True)
            .distinct()
        )
        choices = []
        for value in values:
            if value is None:
                continue
            if value == value.to_integral_value():
                label = f"{value.quantize(Decimal('1'))} мм"
            else:
                label = f"{value.normalize()} мм"
            choices.append((format(value, "f"), label))
        return choices

    def filter_queryset(self, queryset, values):
        parsed = []
        for raw in values:
            try:
                parsed.append(Decimal(str(raw).replace(",", ".")))
            except (InvalidOperation, TypeError, ValueError):
                continue
        if not parsed:
            return queryset
        return queryset.filter(sheet_thickness_mm__in=parsed)


@admin.register(ProductGroup)
class ProductGroupAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    change_list_template = "admin/core/productgroup/change_list.html"
    change_form_template = "admin/core/productgroup/change_form.html"
    list_display = ("name", "products_count", "description_short")
    list_display_links = ("name",)
    search_fields = ("name", "description")
    list_filter = (WarehouseNavFlagFilter,)
    fieldsets = (
        (None, {"fields": ("name",)}),
        (
            "Описание",
            {
                "classes": ("collapse",),
                "fields": ("description",),
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _products_count=Count(
                "products",
                filter=Q(products__product_kind=Product.PRODUCT_KIND_GOODS),
            )
        )

    def get_search_results(self, request, queryset, search_term):
        term = (search_term or "").strip()
        if not term:
            return queryset.order_by("name"), False
        needle = term.casefold().replace("ё", "е")
        matched_ids = [
            group.pk
            for group in queryset
            if needle in (group.name or "").casefold().replace("ё", "е")
            or needle in (group.description or "").casefold().replace("ё", "е")
        ]
        return queryset.filter(pk__in=matched_ids).order_by("name"), False

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["productgroup_wh"] = request.GET.get("wh", "")
        return super().changelist_view(request, extra_context)

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        if obj is not None:
            count = obj.products.filter(product_kind=Product.PRODUCT_KIND_GOODS).count()
            params = {"product_kind": Product.PRODUCT_KIND_GOODS, "product_group": obj.pk}
            if request.GET.get("wh"):
                params["wh"] = request.GET.get("wh")
            context["products_of_group_count"] = count
            context["products_of_group_url"] = (
                reverse("admin:core_product_changelist") + "?" + urlencode(params)
            )
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url, obj=obj
        )

    @admin.display(description="Карт.", ordering="_products_count")
    def products_count(self, obj):
        count = getattr(obj, "_products_count", None)
        if count is None:
            count = (
                obj.products.filter(product_kind=Product.PRODUCT_KIND_GOODS).count()
                if obj and obj.pk
                else 0
            )
        return format_html('<span class="mg-card-count">{} карт.</span>', count)

    @admin.display(description="Описание")
    def description_short(self, obj):
        text = (obj.description or "").strip() if obj else ""
        if not text:
            return mark_safe('<span class="mg-card-empty"></span>')
        if len(text) > 80:
            text = text[:79] + "…"
        return format_html('<div class="mg-card-types">{}</div>', text)


@admin.register(ServiceGroup)
class ServiceGroupAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = ("name", "services_count", "description_short")
    search_fields = ("name", "description")
    filter_horizontal = ("services",)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("services")

    @admin.display(description="Услуг в группе")
    def services_count(self, obj):
        return obj.services.count() if obj.pk else 0

    @admin.display(description="Описание")
    def description_short(self, obj):
        if not obj or not obj.description:
            return "—"
        return obj.description[:50] + "…" if len(obj.description) > 50 else obj.description

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "services":
            kwargs["queryset"] = Product.objects.filter(product_kind=Product.PRODUCT_KIND_SERVICE).order_by("name")
        return super().formfield_for_manytomany(db_field, request, **kwargs)


class PriceListColumnInline(admin.TabularInline):
    model = PriceListColumn
    extra = 1
    ordering = ("order",)


@admin.action(description="Дополнить из номенклатуры")
def fill_price_list_from_catalog(modeladmin, request, queryset):
    from decimal import Decimal
    for pl in queryset:
        base_field = {"purchase": "purchase_price", "planned": "planned_price", "min": "min_price"}.get(
            pl.base_price_type, "planned_price"
        )
        columns = list(pl.columns.all().order_by("order", "pk"))
        if not columns:
            continue
        for product in Product.objects.all().order_by("name"):
            base = getattr(product, base_field) or Decimal("0")
            for col in columns:
                if col.use_percent and col.discount_markup_percent is not None:
                    price = (base * (Decimal("1") + col.discount_markup_percent / Decimal("100"))).quantize(
                        Decimal("0.01")
                    )
                else:
                    price = None
                PriceListEntry.objects.get_or_create(
                    price_list=pl, product=product, column=col,
                    defaults={"price": price},
                )
    messages.success(request, "Прайс-листы дополнены из номенклатуры.")


@admin.action(description="Дополнить из остатков")
def fill_price_list_from_stock(modeladmin, request, queryset):
    from decimal import Decimal
    from django.db.models import Sum
    product_ids = set(
        ProductStock.objects.values("product_id")
        .annotate(total=Sum("quantity"))
        .filter(total__gt=0)
        .values_list("product_id", flat=True)
    )
    products = Product.objects.filter(pk__in=product_ids).order_by("name")
    for pl in queryset:
        base_field = {"purchase": "purchase_price", "planned": "planned_price", "min": "min_price"}.get(
            pl.base_price_type, "planned_price"
        )
        for col in pl.columns.all().order_by("order", "pk"):
            for product in products:
                base = getattr(product, base_field) or Decimal("0")
                if col.use_percent and col.discount_markup_percent is not None:
                    price = (base * (Decimal("1") + col.discount_markup_percent / Decimal("100"))).quantize(
                        Decimal("0.01")
                    )
                else:
                    price = None
                PriceListEntry.objects.get_or_create(
                    price_list=pl, product=product, column=col,
                    defaults={"price": price},
                )
    messages.success(request, "Прайс-листы дополнены из остатков на складе.")


@admin.register(PriceListColumn)
class PriceListColumnAdmin(admin.ModelAdmin):
    list_display = ("name", "price_list", "order", "discount_markup_percent", "use_percent")
    list_filter = ("price_list",)
    search_fields = ("name",)
    ordering = ("price_list", "order")


@admin.register(PriceList)
class PriceListAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = ("number_display", "name", "time_display", "base_price_type", "comment_short")
    list_display_links = ("number_display", "name")
    list_filter = ("base_price_type",)
    search_fields = ("name", "comment")
    inlines = [PriceListColumnInline]
    actions = [fill_price_list_from_catalog, fill_price_list_from_stock]
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"
    change_list_template = "admin/core/pricelist/change_list.html"

    @admin.display(description="№")
    def number_display(self, obj):
        return obj.pk if obj else ""

    @admin.display(description="Время")
    def time_display(self, obj):
        if not obj or not obj.created_at:
            return "—"
        from django.utils.formats import date_format
        return date_format(obj.created_at, "DATETIME_FORMAT")

    @admin.display(description="Комментарий")
    def comment_short(self, obj):
        if not obj or not obj.comment:
            return "—"
        return obj.comment[:50] + "…" if len(obj.comment) > 50 else obj.comment


@admin.register(PriceListEntry)
class PriceListEntryAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = ("price_list", "product_name", "column", "price")
    list_filter = ("price_list", "column")
    search_fields = ("product__name", "product__article", "product__code")
    autocomplete_fields = ("price_list", "product", "column")

    @admin.display(description="Наименование")
    def product_name(self, obj):
        """Наименование из справочника товаров."""
        return obj.product.name if obj and obj.product_id else "—"


@admin.register(Product)
class ProductAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "article",
        "product_group",
        "unit",
        "area_m2_display",
        "purchase_price",
        "planned_price",
        "min_price",
        "min_stock",
        "photo_thumb",
    )
    list_display_links = ("name",)
    list_filter = ("product_kind", "track_lots", WarehouseNavFlagFilter)
    search_fields = (
        "name",
        "category",
        "article",
        "code",
        "external_code",
        "barcodes__value",
        "product_group__name",
    )
    autocomplete_fields = ("supplier",)
    inlines = [ProductGalleryImageInline, ProductModificationInline, ProductAnalogInline, ProductBarcodeInline]
    readonly_fields = (
        "sheet_area_mm2",
        "sheet_area_cm2",
        "images_section_hint",
        "packaging_tab_placeholder",
    )
    change_list_template = "admin/core/product/change_list.html"
    change_form_template = "admin/core/product/change_form.html"

    def get_urls(self):
        info = self.model._meta.app_label, self.model._meta.model_name
        custom = [
            path(
                "tc-meta/<int:object_id>/",
                self.admin_site.admin_view(self.techcard_inline_meta_json),
                name="%s_%s_techcard_inline_meta" % info,
            ),
        ]
        return custom + super().get_urls()

    def techcard_inline_meta_json(self, request, object_id):
        """Ед. изм., код, артикул и площадь для зеркала позиций техкарты."""
        if not request.user.is_staff:
            return JsonResponse({"error": "forbidden"}, status=403)
        try:
            p = Product.objects.only(
                "unit", "code", "article", "name", "area_m2_manual"
            ).get(pk=object_id)
        except Product.DoesNotExist:
            return JsonResponse({"error": "not found"}, status=404)
        return JsonResponse(
            {
                "unit": (p.unit or "").strip(),
                "code": (p.code or "").strip(),
                "article": (p.article or "").strip(),
                "name": (p.name or "").strip(),
                "area_m2": (
                    ""
                    if p.area_m2_manual is None
                    else format(p.area_m2_manual, "f")
                ),
            }
        )

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.normalized_uom_kind() == "piece":
            if "length_m_manual" not in fields:
                fields.append("length_m_manual")
            if "area_m2_manual" not in fields:
                fields.append("area_m2_manual")
        return fields

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "unit":
            kwargs["widget"] = UnitDatalistTextWidget()
        if db_field.name == "product_group":
            kwargs["label"] = "Группа"
        if db_field.name == "unit":
            kwargs["label"] = "Единица измерения"
        if db_field.name == "country":
            kwargs["label"] = "Страна"
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Не autocomplete: Select2/AJAX в узкой сетке карточки часто не показывает список и текущее значение.
        if db_field.name == "product_group":
            kwargs["queryset"] = ProductGroup.objects.all().order_by("name")
        if db_field.name == "material_group":
            kwargs["queryset"] = MaterialGroup.objects.all().order_by("name")
        if db_field.name == "supplier":
            kwargs["label"] = "Поставщик"
            kwargs["queryset"] = _organization_supplier_queryset(request, Product)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_changeform_initial_data(self, request):
        """С «+ Товар» / «+ Услуга» передаётся ?product_kind=… — подставляем в форму добавления."""
        initial = super().get_changeform_initial_data(request)
        kind = request.GET.get("product_kind")
        if kind in (
            Product.PRODUCT_KIND_SERVICE,
            Product.PRODUCT_KIND_GOODS,
            Product.PRODUCT_KIND_MATERIAL,
        ):
            initial = {**initial, "product_kind": kind}
        return initial

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        context.setdefault(
            "operation_types_data",
            list(OperationType.objects.order_by("pk").values("id", "name", "result_adjective")),
        )
        context.setdefault("material_avg_unit_prices", _material_average_unit_prices_map())
        if obj is not None and obj.pk:
            tc = obj._primary_tech_card_for_cost()
            context["product_planned_cost_breakdown"] = {
                "materials": format(obj.planned_material_cost, "f"),
                "components": format(
                    tc.planned_component_cost_per_unit() if tc is not None else Decimal("0"),
                    "f",
                ),
                "labor": format(obj.planned_labor_cost, "f"),
                "overhead": format(obj.planned_overhead_cost, "f"),
                "cut": format(obj.planned_cut_cost, "f"),
                "total": format(obj.planned_total_cost, "f"),
            }
        # Не {% url %} в шаблоне: при NoReverseMatch шаблон падает с 500.
        try:
            context["supplier_new_org_url"] = reverse("admin:core_organization_add")
        except NoReverseMatch:
            context["supplier_new_org_url"] = ""
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Фильтры дерева (товары / услуги / материалы) — только на странице списка.
        # На /change/<id>/ в URL нет ?product_kind= — иначе queryset режется до «товары»,
        # get_object не находит услугу/материал → «Товар с ID … не существует» и редирект на главную.
        rm = getattr(request, "resolver_match", None)
        if rm is None or not str(rm.url_name).endswith("_changelist"):
            return qs

        kind = request.GET.get("product_kind")

        def annotate_catalog_material_pk(q):
            """Совпадение по имени с core.Material (первый по pk); без состояния на ModelAdmin — безопасно при параллельных запросах."""
            if kind != Product.PRODUCT_KIND_MATERIAL:
                return q
            mat_sq = (
                Material.objects.filter(name__iexact=OuterRef("name"))
                .order_by("pk")
                .values("pk")[:1]
            )
            return q.annotate(_catalog_material_pk=Subquery(mat_sq))

        if kind == Product.PRODUCT_KIND_SERVICE:
            qs = qs.filter(product_kind=Product.PRODUCT_KIND_SERVICE)
            sg = request.GET.get("service_group")
            if sg == "" or sg == "none":
                return qs.annotate(_svc_group_count=Count("service_groups")).filter(
                    _svc_group_count=0
                )
            if sg:
                try:
                    return qs.filter(service_groups__id=int(sg)).distinct()
                except (ValueError, TypeError):
                    pass
            return qs

        if kind == Product.PRODUCT_KIND_MATERIAL:
            qs = qs.filter(product_kind=Product.PRODUCT_KIND_MATERIAL)
            mg = request.GET.get("material_group")
            if mg == "" or mg == "none":
                return annotate_catalog_material_pk(qs.filter(material_group__isnull=True))
            if mg:
                try:
                    return annotate_catalog_material_pk(qs.filter(material_group_id=int(mg)))
                except (ValueError, TypeError):
                    pass
            return annotate_catalog_material_pk(qs)

        # по умолчанию и при product_kind=goods — только товары
        qs = qs.filter(product_kind=Product.PRODUCT_KIND_GOODS).select_related("product_group")
        return qs.annotate(
            _stock_qty=Coalesce(
                Sum("warehouse_stocks__quantity"),
                Value(0),
                output_field=DecimalField(max_digits=16, decimal_places=3),
            )
        )

    def get_list_filter(self, request):
        kind = request.GET.get("product_kind")
        if kind not in (Product.PRODUCT_KIND_SERVICE, Product.PRODUCT_KIND_MATERIAL):
            return (
                ProductKindNavFilter,
                ProductGroupMultiFilter,
                ProductThicknessMultiFilter,
                WarehouseNavFlagFilter,
            )
        return ("product_kind", "track_lots", WarehouseNavFlagFilter)

    def get_list_display(self, request):
        kind = request.GET.get("product_kind")
        if kind not in (Product.PRODUCT_KIND_SERVICE, Product.PRODUCT_KIND_MATERIAL):
            return (
                "photo_thumb",
                "name",
                "product_group",
                "group_params",
                "unit",
                "stock_qty",
            )
        cols = list(super().get_list_display(request))
        if request.GET.get("product_kind") == Product.PRODUCT_KIND_MATERIAL:
            try:
                idx = cols.index("product_group")
                cols[idx] = "material_group"
            except ValueError:
                cols.append("material_group")
            try:
                cols.insert(cols.index("name") + 1, "material_catalog_ref_link")
            except ValueError:
                cols.append("material_catalog_ref_link")
        return cols

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["product_groups"] = ProductGroup.objects.all().order_by("name")
        extra_context["material_groups"] = MaterialGroup.objects.all().order_by("name")
        extra_context["service_groups"] = ServiceGroup.objects.all().order_by("name")
        extra_context["current_product_group"] = request.GET.get("product_group")
        extra_context["current_material_group"] = request.GET.get("material_group")
        extra_context["current_service_group"] = request.GET.get("service_group")
        extra_context["current_product_kind"] = request.GET.get("product_kind")
        extra_context["product_list_as_cards"] = request.GET.get("product_kind") not in (
            Product.PRODUCT_KIND_SERVICE,
            Product.PRODUCT_KIND_MATERIAL,
        )
        return super().changelist_view(request, extra_context)

    @admin.display(description="Справочник", ordering="_catalog_material_pk")
    def material_catalog_ref_link(self, obj):
        mid = getattr(obj, "_catalog_material_pk", None)
        if mid is None:
            return "—"
        try:
            url = reverse("admin:core_material_change", args=[mid])
        except NoReverseMatch:
            return "—"
        return format_html('<a href="{}">Открыть</a>', url)
    fieldsets = (
        ("Основное", {
            "classes": ("product-form-col-main",),
            "description": _PRODUCT_MAIN_FIELDSET_GROUP_HEADING,
            "fields": (
                "name",
                "product_kind",
                "material_group",
                "category",
            ),
        }),
        (
            "Единицы и габариты",
            {
                "classes": ("compact-uom", "product-form-col-uom", "product-tabs-anchor"),
                "fields": (
                    (
                        "length_m_manual",
                        "sheet_length_mm",
                        "sheet_width_mm",
                        "sheet_thickness_mm",
                        "area_m2_manual",
                        "sheet_area_cm2",
                        "sheet_area_mm2",
                    ),
                ),
                "description": _PRODUCT_UOM_FIELDSET_DESCRIPTION,
            },
        ),
        (
            "Общие данные",
            {
                "classes": ("wide", "product-fs-general", "product-form-full"),
                "fields": (
                    "description",
                    "product_group",
                    "country",
                    "supplier",
                    "article",
                    "code",
                    "external_code",
                    "unit",
                    "weight_kg",
                    "volume",
                    "vat_rate_percent",
                ),
            },
        ),
        (
            "Изображения",
            {
                "classes": ("wide", "product-fs-images", "product-form-full"),
                "fields": ("images_section_hint",),
                "description": "До 15 фотографий. Первое по порядку сортировки — миниатюра в списке номенклатуры.",
            },
        ),
        (
            "Цены",
            {
                "classes": (
                    "wide",
                    "product-form-col-prices",
                    "product-prices-tabs-host",
                    "product-extra-fs",
                    "product-extra-fs--prices",
                    "product-form-full",
                ),
                "fields": ("purchase_price", "planned_price", "min_price", "planned_markup_percent"),
            },
        ),
        (
            "Упаковка",
            {
                "classes": ("wide", "product-extra-fs", "product-extra-fs--packaging", "product-form-full"),
                "fields": ("packaging_tab_placeholder",),
                "description": "Виды упаковки, единицы в упаковке — раздел будет расширен.",
            },
        ),
        ("Остатки и учёт", {
            "classes": ("wide", "product-extra-fs", "product-extra-fs--stock", "product-form-full"),
            "fields": ("min_stock", "track_lots"),
        }),
    )

    def save_model(self, request, obj, form, change):
        if obj.product_kind == Product.PRODUCT_KIND_MATERIAL:
            obj.product_group_id = None
        else:
            obj.material_group_id = None
        super().save_model(request, obj, form, change)
        # Складской Material — источник для техкарты и модалки; номенклатура «Материал» подтягивает группу туда.
        sync_catalog_material_from_product_nomenclature(obj)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        obj = form.instance
        if obj.pk:
            first_g = (
                ProductGalleryImage.objects.filter(product_id=obj.pk)
                .order_by("sort_order", "pk")
                .first()
            )
            if first_g and first_g.image:
                if obj.photo != first_g.image:
                    obj.photo = first_g.image
                    obj.save(update_fields=["photo"])
        if not obj.pk or obj.product_kind != Product.PRODUCT_KIND_GOODS:
            return
        obj = (
            Product.objects.prefetch_related(
                Prefetch(
                    "materials",
                    queryset=ProductMaterial.objects.select_related("material").order_by("pk"),
                ),
                Prefetch(
                    "labor_norms",
                    queryset=ProductLabor.objects.select_related("operation_type").order_by("pk"),
                ),
            ).get(pk=obj.pk)
        )
        if obj.apply_composed_goods_identity():
            obj.save()

    @admin.display(description="Параметры")
    def group_params(self, obj):
        items = product_card_params(obj)
        if not items:
            return "—"
        return format_html(
            '<ul class="laser-product-card-params">{}</ul>',
            format_html_join(
                "",
                '<li><span class="k">{}</span> <span class="v">{}</span></li>',
                items,
            ),
        )

    @admin.display(description="Ост.", ordering="_stock_qty")
    def stock_qty(self, obj):
        return _card_param_text(getattr(obj, "_stock_qty", None))

    @admin.display(description="Пл. в м²")
    def area_m2_display(self, obj):
        if not obj or obj.area_m2_manual is None:
            return "—"
        v = obj.area_m2_manual.quantize(Decimal("0.01"))
        return format(v, ".2f")

    @admin.display(description="Фото")
    def photo_thumb(self, obj):
        if not obj or not obj.photo:
            return "—"
        try:
            url = obj.photo.url
        except (ValueError, OSError):
            return "—"
        return format_html(
            '<img src="{}" width="72" height="72" alt="" />',
            url,
        )

    @admin.display(description="")
    def images_section_hint(self, obj):
        return mark_safe(
            '<p class="help" style="margin:0 0 0.5rem">Загрузите фото ниже (не более 15).</p>'
        )

    @admin.display(description="")
    def packaging_tab_placeholder(self, obj):
        return mark_safe('<p class="help" style="margin:0">Раздел в разработке.</p>')


@admin.register(OperationType)
class OperationTypeAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = ("name", "result_adjective", "hourly_rate")
    search_fields = ("name", "result_adjective")


@admin.register(Employee)
class EmployeeAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = ("full_name", "user", "position", "hourly_rate")
    search_fields = ("full_name", "position", "user__username")
    list_filter = ("position",)
    raw_id_fields = ("user",)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 1


@admin.action(description="Создать производственные задания")
def create_production_assignments_from_orders(modeladmin, request, queryset):
    created = 0
    reused = 0
    errors = []

    orders = queryset.prefetch_related("items__product")
    for order in orders:
        items = list(order.items.all())
        if not items:
            errors.append(f"Заказ №{order.pk}: нет позиций для производства.")
            continue
        for item in items:
            try:
                _assignment, is_created = ProductionAssignment.create_from_order_item(item)
                if is_created:
                    created += 1
                else:
                    reused += 1
            except ValueError as exc:
                errors.append(f"Заказ №{order.pk}, позиция #{item.pk}: {exc}")

    if created:
        messages.success(request, f"Создано производственных заданий: {created}.")
    if reused:
        messages.info(request, f"Найдено уже существующих активных заданий: {reused}.")
    if errors:
        messages.error(request, "Ошибки: " + "; ".join(errors[:5]))


@admin.register(Order)
class OrderAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    change_list_template = "admin/core/order/change_list.html"
    change_form_template = "admin/core/order/change_form.html"
    list_display = ("id", "customer_name", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("customer_name", "comment")
    search_help_text = "Клиент или комментарий"
    inlines = [OrderItemInline]
    actions = [create_production_assignments_from_orders]

    def changelist_view(self, request, extra_context=None):
        from urllib.parse import urlencode

        extra_context = extra_context or {}
        qcopy = request.GET.copy()
        qcopy.pop("status__exact", None)
        qcopy.pop("p", None)
        extra_context["order_list_url"] = reverse("admin:core_order_changelist")
        extra_context["order_sidebar_qs_base"] = urlencode(qcopy, doseq=True)
        extra_context["order_status_selected"] = request.GET.get("status__exact", "") or ""
        count_by_status = {
            row["status"]: row["c"]
            for row in Order.objects.values("status").annotate(c=Count("id"))
        }
        extra_context["order_status_sidebar"] = [
            {"code": code, "label": label, "count": count_by_status.get(code, 0)}
            for code, label in Order.STATUS_CHOICES
        ]
        extra_context["order_total_count"] = Order.objects.count()
        return super().changelist_view(request, extra_context)


@admin.register(CustomerInvoice)
class CustomerInvoiceAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = (
        "number",
        "issue_date",
        "customer_name",
        "amount",
        "status",
        "production_request",
    )
    list_filter = ("status", "issue_date")
    search_fields = ("number", "customer_name", "customer_email", "purpose")
    autocomplete_fields = ("production_request", "order", "our_organization", "created_by")
    readonly_fields = ("number", "sent_to_chat_at", "created_at", "updated_at")


@admin.register(BankPaymentOrder)
class BankPaymentOrderAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = (
        "number",
        "payment_date",
        "customer_invoice",
        "amount",
        "status",
        "external_operation_id",
        "sent_at",
    )
    list_filter = ("status", "payment_date", "sent_at")
    search_fields = ("number", "customer_invoice__number", "recipient_name", "external_operation_id")
    autocomplete_fields = ("customer_invoice", "created_by")
    readonly_fields = ("number", "payload", "bank_response", "sent_at", "created_at", "updated_at")


@admin.action(description="Конвертировать в заказ покупателя")
def convert_request_to_order(modeladmin, request, queryset):
    converted = 0
    skipped = 0
    for req in queryset:
        if req.status == ProductionRequest.STATUS_CONVERTED:
            skipped += 1
            continue
        comment_parts = [
            f"production_request_id={req.pk}",
            f"phone={req.phone}",
            f"email={req.email}",
        ]
        if req.deadline:
            comment_parts.append(f"deadline={req.deadline.isoformat()}")
        if req.material_preferences:
            comment_parts.append(f"material_preferences={req.material_preferences}")
        if req.specs:
            comment_parts.append(f"specs={req.specs}")
        if req.comment:
            comment_parts.append(f"client_comment={req.comment}")
        if req.manager_comment:
            comment_parts.append(f"manager_comment={req.manager_comment}")

        order = Order.objects.create(
            customer_name=req.customer_name,
            comment="; ".join(comment_parts),
        )
        if req.product_id:
            OrderItem.objects.create(
                order=order,
                product=req.product,
                quantity=max(1, req.quantity),
                planned_price=req.product.planned_price,
            )
        req.status = ProductionRequest.STATUS_CONVERTED
        req.manager_comment = (
            ((req.manager_comment + "\n") if req.manager_comment else "")
            + f"Конвертирован в заказ покупателя №{order.pk}."
        )
        req.save(update_fields=["status", "manager_comment", "updated_at"])
        converted += 1
    if converted:
        messages.success(request, f"Конвертировано запросов: {converted}.")
    if skipped:
        messages.info(request, f"Пропущено уже конвертированных: {skipped}.")


@admin.register(ProductionRequest)
class ProductionRequestAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "request_title",
        "customer_name",
        "quantity",
        "layout_file_link",
        "layout_scan_status",
        "status",
        "created_at",
    )
    list_filter = ("status", "layout_scan_status", "created_at")
    search_fields = ("customer_name", "request_title", "phone", "email", "specs", "comment")
    autocomplete_fields = ("product", "user")
    readonly_fields = (
        "layout_scan_status",
        "layout_scan_result",
        "layout_scanned_at",
        "layout_is_quarantined",
        "layout_quarantine_path",
        "created_at",
        "updated_at",
    )
    actions = [convert_request_to_order]

    @admin.display(description="Макет")
    def layout_file_link(self, obj):
        if not obj.layout_file:
            return "—"
        return format_html('<a href="{}" target="_blank" rel="noopener">Открыть</a>', obj.layout_file.url)


class ProductionRequestMessageInline(admin.TabularInline):
    model = ProductionRequestMessage
    extra = 0
    autocomplete_fields = ("author",)
    readonly_fields = ("created_at",)


ProductionRequestAdmin.inlines = [ProductionRequestMessageInline]


class ContractVersionInline(admin.TabularInline):
    model = ContractVersion
    extra = 0
    readonly_fields = ("version_number", "generated_text", "generated_file", "created_by", "created_at")
    can_delete = False


@admin.action(description="Сгенерировать новую версию договора")
def generate_contract_version(modeladmin, request, queryset):
    generated = 0
    for contract in queryset:
        last_version = contract.versions.order_by("-version_number").first()
        next_version = (last_version.version_number if last_version else 0) + 1
        generated_text = (
            f"ДОГОВОР № {contract.number}\n"
            f"Дата: {contract.contract_date:%d.%m.%Y}\n"
            f"Тип: {contract.get_contract_type_display()}\n"
            f"Статус: {contract.get_status_display()}\n\n"
            f"Наша организация: {contract.our_organization.name}\n"
            f"ИНН: {contract.our_organization.inn}\n"
            f"Адрес: {contract.our_organization.legal_address}\n\n"
            f"Контрагент: {contract.counterparty.name}\n"
            f"ИНН: {contract.counterparty.inn}\n"
            f"Адрес: {contract.counterparty.legal_address}\n\n"
            f"Предмет: {contract.subject or '—'}\n"
            f"Условия оплаты: {contract.payment_terms or '—'}\n"
            f"Условия поставки: {contract.delivery_terms or '—'}\n"
            f"Комментарий: {contract.comment or '—'}\n"
        )
        version = ContractVersion(
            contract=contract,
            version_number=next_version,
            generated_text=generated_text,
            created_by=request.user if request.user.is_authenticated else None,
        )
        filename = f"contract_{contract.pk}_v{next_version}.txt"
        version.generated_file.save(filename, ContentFile(generated_text.encode("utf-8")), save=False)
        version.save()
        generated += 1
    if generated:
        messages.success(request, f"Сгенерировано версий договоров: {generated}.")


@admin.register(Contract)
class ContractAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = (
        "number",
        "contract_date",
        "contract_type",
        "status",
        "our_organization",
        "counterparty",
        "valid_until",
    )
    list_filter = ("contract_type", "status", "contract_date", "valid_until")
    search_fields = ("number", "subject", "our_organization__name", "counterparty__name")
    autocomplete_fields = ("our_organization", "counterparty")
    readonly_fields = ("created_at", "updated_at")
    inlines = [ContractVersionInline]
    actions = [generate_contract_version]


@admin.register(EmailVerification)
class EmailVerificationAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = ("id", "user", "is_verified", "sent_at", "verified_at", "updated_at")
    list_filter = ("is_verified", "sent_at", "verified_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AdminInvite)
class AdminInviteAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = ("id", "email", "role", "sent_at", "accepted_at", "created_at", "updated_at")
    list_filter = ("role", "sent_at", "accepted_at")
    search_fields = ("email",)
    readonly_fields = ("token", "sent_at", "accepted_at", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        is_new = not change
        super().save_model(request, obj, form, change)
        if is_new and obj.sent_at is None:
            from .admin_invite import send_admin_invite_email

            send_admin_invite_email(request, obj)


@admin.register(UserProfile)
class UserProfileAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = ("id", "user", "phone", "updated_at")
    search_fields = ("user__username", "user__email", "phone")
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")


# --- Заказ на производство (базовый способ) ---


class MaterialReservationInline(admin.TabularInline):
    model = MaterialReservation
    extra = 0
    readonly_fields = ("warehouse", "material", "quantity")
    can_delete = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.action(description="Зарезервировать материалы")
def reserve_materials_action(modeladmin, request, queryset):
    errors = []
    done = 0
    for order in queryset.filter(status=ProductionOrder.STATUS_DRAFT):
        try:
            order.reserve_materials()
            done += 1
        except Exception as e:
            errors.append(f"№{order.pk}: {e}")
    if done:
        messages.success(request, f"Зарезервировано заказов: {done}.")
    if errors:
        messages.error(request, "Ошибки: " + "; ".join(errors[:5]))


@admin.action(description="Снять резерв материалов")
def release_reservation_action(modeladmin, request, queryset):
    for order in queryset:
        order.release_reservation()
    messages.success(request, "Резерв снят у выбранных заказов.")


@admin.register(ProductionOrder)
class ProductionOrderAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "tech_card",
        "quantity",
        "material_warehouse",
        "product_warehouse",
        "status",
        "date_planned",
        "date_deadline",
        "created_at",
    )
    list_filter = ("status", "material_warehouse", "product_warehouse")
    search_fields = ("tech_card__name", "comment")
    autocomplete_fields = ("tech_card", "product_warehouse", "material_warehouse")
    inlines = [MaterialReservationInline]
    actions = [reserve_materials_action, release_reservation_action]
    readonly_fields = ("created_at",)
    date_hierarchy = "date_planned"


# --- Разбор изделия (базовый способ) ---


@admin.action(description="Провести разбор")
def conduct_disassembly_action(modeladmin, request, queryset):
    errors = []
    done = 0
    for doc in queryset.filter(status=ProductDisassembly.STATUS_DRAFT):
        try:
            doc.conduct()
            done += 1
        except ValueError as e:
            errors.append(f"№{doc.pk}: {e}")
    if done:
        messages.success(request, f"Проведено разборов: {done}.")
    if errors:
        messages.error(request, "Ошибки: " + "; ".join(errors[:5]))


@admin.register(ProductDisassembly)
class ProductDisassemblyAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "tech_card",
        "quantity",
        "product_warehouse",
        "material_warehouse",
        "status",
        "date",
        "created_at",
    )
    list_filter = ("status", "product_warehouse", "material_warehouse")
    search_fields = ("tech_card__name", "comment")
    autocomplete_fields = ("tech_card", "product_warehouse", "material_warehouse")
    actions = [conduct_disassembly_action]
    date_hierarchy = "date"


# --- Этапы производства и техпроцесс (расширенный способ) ---


class TechProcessStageInlineForm(forms.ModelForm):
    """Порядок задаётся перетаскиванием строк; поле order — скрытое."""

    class Meta:
        model = TechProcessStage
        fields = "__all__"
        widgets = {"order": forms.HiddenInput()}


class TechProcessStageInline(admin.TabularInline):
    model = TechProcessStage
    form = TechProcessStageInlineForm
    template = "admin/core/tech_process_stages/tabular.html"
    extra = 0
    autocomplete_fields = ("production_stage",)
    ordering = ("order",)
    fields = ("order", "production_stage", "next_stage_hint")
    readonly_fields = ("next_stage_hint",)
    verbose_name = "этап производства"
    verbose_name_plural = "Этапы производства"

    class Media:
        css = {"all": ("core/admin/tech_process_stages_inline.css",)}
        js = ("core/admin/tech_process_stages_inline.js",)

    def get_extra(self, request, obj=None, **kwargs):
        # При редактировании — без пустой строки (не удалять её перед сохранением).
        # При создании техпроцесса — одна пустая строка для первого этапа.
        if obj and getattr(obj, "pk", None):
            return 0
        return 1

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related(
            "production_stage", "tech_process"
        )
        return qs.prefetch_related(
            Prefetch(
                "tech_process__techprocessstage_set",
                queryset=TechProcessStage.objects.order_by(
                    "order", "pk"
                ).select_related("production_stage"),
            )
        )

    @admin.display(description="Следующий этап")
    def next_stage_hint(self, obj):
        if obj is None or not getattr(obj, "pk", None):
            return "—"
        if not obj.tech_process_id:
            return "—"
        tp = obj.tech_process
        siblings = list(tp.techprocessstage_set.all())
        siblings.sort(key=lambda s: (s.order, s.pk))
        try:
            idx = next(i for i, s in enumerate(siblings) if s.pk == obj.pk)
        except StopIteration:
            return "—"
        if idx + 1 < len(siblings):
            nxt = siblings[idx + 1].production_stage
            return (getattr(nxt, "name", None) or "").strip() or "—"
        return "По завершении готовая продукция поступит на склад"


def _employee_surname_initials(full_name: str) -> str:
    """ФИО из поля full_name -> «Фамилия И.О.» для списка этапов."""
    s = (full_name or "").strip()
    if not s:
        return "—"
    parts = s.split()
    if len(parts) == 1:
        return parts[0]
    surname = parts[0]
    initials = []
    for part in parts[1:]:
        part = part.strip()
        if not part:
            continue
        if "." in part:
            initials.append(part)
        else:
            initials.append(part[0].upper() + ".")
    return surname + " " + "".join(initials)


@admin.action(description="Копировать выбранные этапы")
def copy_production_stages(modeladmin, request, queryset):
    created = 0
    for stage in queryset:
        new_name = f"Копия: {stage.name}"[:255]
        if ProductionStage.objects.filter(name=new_name).exists():
            suffix = 1
            while ProductionStage.objects.filter(name=f"{new_name} ({suffix})").exists():
                suffix += 1
            new_name = f"{new_name} ({suffix})"[:255]
        new_stage = ProductionStage.objects.create(
            name=new_name,
            sequence=stage.sequence,
            description=stage.description,
            material_warehouse=stage.material_warehouse,
            hourly_rate=stage.hourly_rate,
            cut_rate_per_meter=stage.cut_rate_per_meter,
            track_real_time=stage.track_real_time,
            any_employee_can_execute=stage.any_employee_can_execute,
            master=stage.master,
        )
        new_stage.executors.set(stage.executors.all())
        new_stage.counterparty_executors.set(stage.counterparty_executors.all())
        created += 1
    if created:
        messages.success(request, f"Создано копий этапов: {created}.")


@admin.register(ProductionStage)
class ProductionStageAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "sequence",
        "material_warehouse",
        "hourly_rate",
        "cut_rate_per_meter",
        "track_real_time",
        "executors_changelist_display",
        "master",
    )
    list_editable = ("sequence",)
    list_filter = ("track_real_time", "any_employee_can_execute")
    ordering = ("sequence", "name")
    search_fields = ("name", "description")
    filter_horizontal = ("executors", "counterparty_executors")
    autocomplete_fields = ("material_warehouse", "master")
    actions = [copy_production_stages]
    change_form_template = "admin/core/productionstage/change_form.html"

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("executors")

    @admin.display(description="Кто может выполнять")
    def executors_changelist_display(self, obj):
        if obj.any_employee_can_execute:
            return "Любой"
        emps = list(obj.executors.all())
        if not emps:
            return "—"
        emps.sort(key=lambda e: (e.full_name or "").lower())
        return ", ".join(_employee_surname_initials(e.full_name) for e in emps)

    fieldsets = (
        (None, {
            "fields": ("name", "sequence", "description"),
        }),
        ("Склад и затраты", {
            "fields": (
                "material_warehouse",
                "hourly_rate",
                "cut_rate_per_meter",
                "track_real_time",
            ),
            "description": "Нормо-час — ₽ за час работы этапа (станок/участок). Стоимость метра реза — для лазера: в техкарте укажите норму м на изделие на строке с этим этапом.",
            "classes": ("wide", "compact-two-cols"),
        }),
        ("Исполнители", {
            "fields": (
                "any_employee_can_execute",
                "master",
                "executors",
                "counterparty_executors",
            ),
            "description": "Если «Любой сотрудник может выполнять этап» выключен — в задании можно назначить только указанных сотрудников. Мастер может распределять задания. Контрагенты — подрядчики для этапа или услуги (справочник «Контрагенты»).",
            "classes": ("wide", "executors-tabs"),
        }),
    )

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        try:
            service_choices = [
                [pk, name]
                for pk, name in Product.objects.filter(
                    product_kind=Product.PRODUCT_KIND_SERVICE
                )
                .order_by("name")
                .values_list("pk", "name")
            ]
        except Exception:
            service_choices = []
        extra_context["counterparty_service_choices"] = service_choices
        counterparty_services = {}
        if object_id:
            try:
                for rel in ProductionStageCounterpartyService.objects.filter(
                    production_stage_id=object_id
                ).select_related("organization", "service"):
                    if rel.service_id:
                        counterparty_services[str(rel.organization_id)] = rel.service_id
            except Exception:
                counterparty_services = {}
        extra_context["counterparty_services_initial"] = counterparty_services
        # Autocomplete в шаблоне: core vs production (прокси) — разные app_label/model_name
        meta = self.model._meta
        extra_context["employee_autocomplete_params"] = (
            f"app_label={meta.app_label}&model_name={meta.model_name}&field_name=executors"
        )
        extra_context["counterparty_autocomplete_params"] = (
            f"app_label={meta.app_label}&model_name={meta.model_name}&field_name=counterparty_executors"
        )
        return super().changeform_view(request, object_id, form_url, extra_context)

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        """Гарантируем переменные для шаблона (в т.ч. при ошибках валидации формы)."""
        context.setdefault("counterparty_service_choices", [])
        context.setdefault("counterparty_services_initial", {})
        meta = self.model._meta
        context.setdefault(
            "employee_autocomplete_params",
            f"app_label={meta.app_label}&model_name={meta.model_name}&field_name=executors",
        )
        context.setdefault(
            "counterparty_autocomplete_params",
            f"app_label={meta.app_label}&model_name={meta.model_name}&field_name=counterparty_executors",
        )
        rows = []
        initial = context.get("counterparty_services_initial") or {}
        if obj and getattr(obj, "pk", None):
            try:
                for org in obj.counterparty_executors.all():
                    rows.append(
                        {"org": org, "selected_id": initial.get(str(org.pk))}
                    )
            except Exception:
                rows = []
        context["counterparty_service_rows"] = rows
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url, obj=obj
        )

    def response_change(self, request, obj):
        """После «Сохранить» — в список «Этапы производства» (core или production-прокси)."""
        if request.GET.get("_popup") or request.POST.get("_popup"):
            return super().response_change(request, obj)
        if "_continue" in request.POST or "_addanother" in request.POST:
            return super().response_change(request, obj)
        opts = self.model._meta
        url = reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")
        return HttpResponseRedirect(url)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # Сохранение списка этапов (list_editable) — в POST только formset «form»,
        # без полей counterparty_service_*. Иначе update_or_create(..., service=None)
        # обнуляет услуги у всех контрагентов этапа.
        if "form-TOTAL_FORMS" in request.POST:
            return
        obj = form.instance
        try:
            for org in obj.counterparty_executors.all():
                key = "counterparty_service_%s" % org.pk
                service_id = request.POST.get(key)
                service = None
                if service_id:
                    try:
                        service = Product.objects.get(
                            pk=service_id, product_kind=Product.PRODUCT_KIND_SERVICE
                        )
                    except (ValueError, Product.DoesNotExist):
                        pass
                ProductionStageCounterpartyService.objects.update_or_create(
                    production_stage=obj,
                    organization=org,
                    defaults={"service": service},
                )
            ProductionStageCounterpartyService.objects.filter(
                production_stage=obj
            ).exclude(
                organization__in=obj.counterparty_executors.all()
            ).delete()
        except Exception:
            pass


@admin.action(description="Копировать выбранные техпроцессы")
def copy_tech_processes(modeladmin, request, queryset):
    """Новый техпроцесс с тем же порядком этапов (ссылки на те же этапы справочника)."""
    created = 0
    for tp in queryset:
        new_name = f"Копия: {tp.name}"[:255]
        if TechProcess.objects.filter(name=new_name).exists():
            suffix = 1
            while TechProcess.objects.filter(name=f"{new_name} ({suffix})").exists():
                suffix += 1
            new_name = f"{new_name} ({suffix})"[:255]
        with transaction.atomic():
            new_tp = TechProcess.objects.create(
                name=new_name,
                description=tp.description,
            )
            for tps in tp.techprocessstage_set.order_by("order", "pk"):
                TechProcessStage.objects.create(
                    tech_process=new_tp,
                    production_stage=tps.production_stage,
                    order=tps.order,
                )
        created += 1
    if created:
        messages.success(request, f"Создано копий техпроцессов: {created}.")


@admin.register(TechProcess)
class TechProcessAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name",)
    inlines = [TechProcessStageInline]
    actions = [copy_tech_processes]


# --- Производственное задание (расширенный способ) ---


class ProductionDefectInline(admin.TabularInline):
    model = ProductionDefect
    extra = 0
    autocomplete_fields = ("product",)
    verbose_name = "Документ брака"
    verbose_name_plural = "Брак по этапу"


class ProductionAssignmentItemInline(admin.TabularInline):
    model = ProductionAssignmentItem
    extra = 1
    autocomplete_fields = ("tech_card", "production_stage")
    ordering = ("sequence",)
    fields = (
        "sequence",
        "tech_card",
        "tech_card_edit_link",
        "production_stage",
        "quantity_planned",
        "quantity_produced",
        "status",
        "started_at",
        "completed_at",
    )
    readonly_fields = ("tech_card_edit_link",)

    @admin.display(description="Состав и затраты")
    def tech_card_edit_link(self, obj):
        if not obj or not obj.tech_card_id:
            return "—"
        url = _admin_change_url_for_db_table(
            TechCard,
            obj.tech_card_id,
            self.parent_model._meta.app_label,
        )
        if not url:
            return "—"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Открыть техкарту</a>',
            url,
        )


class ProductionDeviationInline(admin.TabularInline):
    model = ProductionDeviation
    extra = 0
    autocomplete_fields = ("material", "product", "assignment_item")


@admin.action(description="Создать задание снабжения (на полуфабрикаты)")
def create_supply_assignment_action(modeladmin, request, queryset):
    errors = []
    done = 0
    for assignment in queryset:
        if assignment.supply_assignment_id:
            errors.append(f"Задание #{assignment.pk}: снабжение уже создано.")
            continue
        try:
            assignment.create_supply_assignment()
            done += 1
        except Exception as e:
            errors.append(f"Задание #{assignment.pk}: {e}")
    if done:
        messages.success(request, f"Создано заданий снабжения: {done}.")
    if errors:
        messages.error(request, "Ошибки: " + "; ".join(errors[:5]))


_PRODUCTION_ASSIGNMENT_FIELDSET_INTRO_HTML = (
    "<p><strong>Производственное задание</strong> описывает:</p>"
    "<ul style='margin-top:0.35em;margin-bottom:0;'>"
    "<li>какую продукцию и в каком объёме надо произвести, по каким техкартам;</li>"
    "<li>какие для этого потребуются материалы и затраты;</li>"
    "<li>как выполняется задание.</li>"
    "</ul>"
    "<p style='margin-top:0.75em;margin-bottom:0;'>"
    "Можно создать задание на смену, неделю работы или заказ от покупателя. "
    "В документе поэтапно отмечается выполнение (позиции задания и этапы)."
    "</p>"
)


@admin.action(description="Провести выбранные этапы (списание и выпуск)")
def conduct_assignment_items_action(modeladmin, request, queryset):
    errors = []
    done = 0
    for item in queryset.filter(status__in=(ProductionAssignmentItem.STATUS_PENDING, ProductionAssignmentItem.STATUS_IN_PROGRESS)):
        try:
            item.conduct()
            done += 1
        except ValueError as e:
            errors.append(f"Позиция {item.pk}: {e}")
    if done:
        messages.success(request, f"Проведено этапов: {done}.")
    if errors:
        messages.error(request, "Ошибки: " + "; ".join(errors[:5]))


@admin.register(ProductionAssignment)
class ProductionAssignmentAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    change_form_template = "admin/core/productionassignment/change_form.html"
    save_on_top = True
    list_display = (
        "id",
        "name",
        "order",
        "order_item",
        "tech_process",
        "status",
        "supply_assignment",
        "material_warehouse",
        "product_warehouse",
        "date_planned",
        "date_started",
        "date_completed",
        "created_at",
    )
    list_filter = (
        "status",
        "expectation",
        "reserve_materials",
        "tech_process",
        "material_warehouse",
        "product_warehouse",
    )
    search_fields = (
        "name",
        "comment",
        "order__customer_name",
        "order_item__product__name",
    )
    autocomplete_fields = (
        "tech_process",
        "product_warehouse",
        "material_warehouse",
        "order",
    )
    inlines = [ProductionAssignmentItemInline, ProductionDeviationInline]
    readonly_fields = ("created_at", "supply_assignment", "products_summary_display")
    actions = [create_supply_assignment_action]
    date_hierarchy = "date_planned"

    def get_urls(self):
        info = self.model._meta.app_label, self.model._meta.model_name
        custom = [
            path(
                "<int:object_id>/supply/",
                self.admin_site.admin_view(self.supply_view),
                name="%s_%s_supply" % info,
            ),
            path(
                "<int:object_id>/create-supply/",
                self.admin_site.admin_view(self.create_supply_view),
                name="%s_%s_create_supply" % info,
            ),
        ]
        return custom + super().get_urls()

    def supply_view(self, request, object_id: int):
        assignment = get_object_or_404(ProductionAssignment, pk=object_id)
        material_rows = assignment.get_materials_flat_tab_rows()
        material_deficit_rows = []
        for row in material_rows:
            if row["order_qty"] <= Decimal("0"):
                continue
            order_line_cost = (
                (row["order_qty"] * row["unit_cost"]).quantize(Decimal("0.01"))
                if row["unit_cost"]
                else Decimal("0.00")
            )
            material_deficit_rows.append({**row, "order_line_cost": order_line_cost})
        component_rows = []
        for product, qty in assignment.get_component_requirements():
            component_rows.append(
                {
                    "product": product,
                    "quantity": qty,
                    "tech_card": TechCard.objects.filter(product=product).order_by("id").first(),
                }
            )

        if request.method == "POST":
            action = request.POST.get("action")
            if action == "create_supply_assignment":
                if assignment.supply_assignment_id:
                    messages.info(
                        request,
                        f"Задание снабжения уже создано: #{assignment.supply_assignment_id}.",
                    )
                    return HttpResponseRedirect(
                        reverse(
                            "admin:core_productionassignment_change",
                            args=[assignment.supply_assignment_id],
                        )
                    )
                try:
                    supply_assignment = assignment.create_supply_assignment()
                except Exception as exc:
                    messages.error(request, f"Не удалось создать задание снабжения: {exc}")
                    return HttpResponseRedirect(
                        reverse("admin:core_productionassignment_supply", args=[assignment.pk])
                    )
                messages.success(request, f"Создано задание снабжения #{supply_assignment.pk}.")
                return HttpResponseRedirect(
                    reverse("admin:core_productionassignment_change", args=[supply_assignment.pk])
                )

            if action == "create_supplier_po":
                from procurement.models import SupplierPurchaseOrder, SupplierPurchaseOrderLine

                supplier_id = request.POST.get("supplier")
                selected_ids = {
                    int(value)
                    for value in request.POST.getlist("material")
                    if str(value).isdigit()
                }
                selected_rows = [
                    row
                    for row in material_deficit_rows
                    if row["material"].pk in selected_ids and row["order_qty"] > Decimal("0")
                ]
                if not supplier_id:
                    messages.error(request, "Выберите поставщика для заказа материалов.")
                    return HttpResponseRedirect(
                        reverse("admin:core_productionassignment_supply", args=[assignment.pk])
                    )
                if not selected_rows:
                    messages.error(request, "Выберите материалы с дефицитом для заказа поставщику.")
                    return HttpResponseRedirect(
                        reverse("admin:core_productionassignment_supply", args=[assignment.pk])
                    )
                try:
                    supplier = Organization.objects.get(pk=supplier_id, is_supplier=True)
                except Organization.DoesNotExist:
                    messages.error(request, "Выбранный поставщик не найден или не отмечен как поставщик.")
                    return HttpResponseRedirect(
                        reverse("admin:core_productionassignment_supply", args=[assignment.pk])
                    )

                purchase_order = SupplierPurchaseOrder.objects.create(
                    supplier=supplier,
                    comment=f"Снабжение по производственному заданию #{assignment.pk}: {assignment}",
                )
                for row in selected_rows:
                    SupplierPurchaseOrderLine.objects.create(
                        purchase_order=purchase_order,
                        material=row["material"],
                        quantity=row["order_qty"],
                        unit_price=row["unit_cost"] or None,
                    )
                messages.success(
                    request,
                    f"Создан заказ поставщику {purchase_order} на строк: {len(selected_rows)}.",
                )
                return HttpResponseRedirect(
                    reverse("admin:procurement_supplierpurchaseorder_change", args=[purchase_order.pk])
                )

            messages.error(request, "Неизвестное действие снабжения.")
            return HttpResponseRedirect(
                reverse("admin:core_productionassignment_supply", args=[assignment.pk])
            )

        suppliers = Organization.objects.filter(is_supplier=True).order_by("name")
        context = {
            **self.admin_site.each_context(request),
            "title": f"Снабжение: {assignment}",
            "opts": self.model._meta,
            "original": assignment,
            "assignment": assignment,
            "material_rows": material_rows,
            "material_deficit_rows": material_deficit_rows,
            "component_rows": component_rows,
            "suppliers": suppliers,
            "has_supply_assignment": bool(assignment.supply_assignment_id),
            "supply_open_url": (
                reverse("admin:core_productionassignment_change", args=[assignment.supply_assignment_id])
                if assignment.supply_assignment_id
                else ""
            ),
            "change_url": reverse("admin:core_productionassignment_change", args=[assignment.pk]),
        }
        return render(request, "admin/core/productionassignment/supply.html", context)

    def create_supply_view(self, request, object_id: int):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        assignment = get_object_or_404(ProductionAssignment, pk=object_id)
        if assignment.supply_assignment_id:
            messages.info(
                request,
                f"Задание снабжения уже создано: #{assignment.supply_assignment_id}.",
            )
            return HttpResponseRedirect(
                reverse("admin:core_productionassignment_change", args=[assignment.supply_assignment_id])
            )
        try:
            supply_assignment = assignment.create_supply_assignment()
        except Exception as exc:
            messages.error(request, f"Не удалось создать снабжение: {exc}")
            return HttpResponseRedirect(
                reverse("admin:core_productionassignment_change", args=[assignment.pk])
            )
        messages.success(
            request,
            f"Создано задание снабжения #{supply_assignment.pk}.",
        )
        return HttpResponseRedirect(
            reverse("admin:core_productionassignment_change", args=[supply_assignment.pk])
        )

    def get_fieldsets(self, request, obj=None):
        intro = (
            _PRODUCTION_ASSIGNMENT_FIELDSET_INTRO_HTML
            if obj and getattr(obj, "pk", None)
            else ""
        )
        main = (
            None,
            {
                "fields": (
                    "name",
                    "order",
                    "order_item",
                    "tech_process",
                    "product_warehouse",
                    "material_warehouse",
                    "reserve_materials",
                    "expectation",
                    "status",
                    "supply_assignment",
                ),
                "description": intro,
            },
        )
        dates = (
            "Даты",
            {
                "fields": (
                    "date_planned",
                    "date_started",
                    "date_completed",
                    "created_at",
                ),
            },
        )
        comment_fs = ("Комментарий", {"fields": ("comment",)})
        if obj and getattr(obj, "pk", None):
            product_fs = (
                "Продукция",
                {
                    "fields": ("products_summary_display",),
                    "description": "Сводка по выпускаемой продукции и оценка затрат",
                    "classes": ("wide", "pa-fs-hidden",),
                },
            )
            return (main, dates, product_fs, comment_fs)
        return (main, dates, comment_fs)

    @admin.display(description="Продукция (сводка)")
    def products_summary_display(self, obj):
        if not obj or not obj.pk:
            return "—"
        rows = obj.get_products_summary()
        if not rows:
            return "Нет продукции по позициям задания (у техкарт не указано изделие)."
        parts = [
            "<table style='border-collapse: collapse;'>",
            "<tr><th style='text-align:left;padding:4px 8px;'>Изделие</th>"
            "<th style='padding:4px 8px;'>План</th><th style='padding:4px 8px;'>Выпуск</th>"
            "<th style='padding:4px 8px;'>Брак</th><th style='padding:4px 8px;'>Годная</th>"
            "<th style='padding:4px 8px;'>Оценка затрат (₽)</th></tr>",
        ]
        for r in rows:
            parts.append(
                f"<tr><td style='padding:4px 8px;'>{r['product']}</td>"
                f"<td style='padding:4px 8px;'>{r['planned']}</td>"
                f"<td style='padding:4px 8px;'>{r['produced']}</td>"
                f"<td style='padding:4px 8px;'>{r['defect']}</td>"
                f"<td style='padding:4px 8px;'>{r['good']}</td>"
                f"<td style='padding:4px 8px;'>{r['cost_estimate']}</td></tr>"
            )
        parts.append("</table>")
        return mark_safe("".join(parts))

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        ro = context.get("original")
        if ro and getattr(ro, "pk", None):
            context["pa_materials_flat_rows"] = ro.get_materials_flat_tab_rows()
            context["pa_doc_code"] = ro.get_document_code_display()
            context["pa_costs_summary"] = ro.get_costs_summary_for_ui()
            context["pa_products_rows"] = ro.get_products_summary()
            context["pa_supply_create_url"] = reverse(
                "admin:core_productionassignment_supply", args=[ro.pk]
            )
            context["pa_supply_open_url"] = (
                reverse("admin:core_productionassignment_change", args=[ro.supply_assignment_id])
                if ro.supply_assignment_id
                else ""
            )
        else:
            context["pa_materials_flat_rows"] = []
            context["pa_doc_code"] = ""
            context["pa_costs_summary"] = {
                "materials": Decimal("0"),
                "labor": Decimal("0"),
                "cut": Decimal("0"),
                "total": Decimal("0"),
            }
            context["pa_products_rows"] = []
            context["pa_supply_create_url"] = ""
            context["pa_supply_open_url"] = ""
        return super().render_change_form(
            request,
            context,
            add=add,
            change=change,
            form_url=form_url,
            obj=obj,
        )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.sync_assignment_material_reservations()


@admin.register(ProductionAssignmentItem)
class ProductionAssignmentItemAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "assignment",
        "production_stage",
        "tech_card",
        "sequence",
        "quantity_planned",
        "quantity_produced",
        "defect_quantity_display",
        "good_quantity_display",
        "status",
        "started_at",
        "completed_at",
    )
    list_filter = ("status", "assignment", "production_stage")
    search_fields = ("id", "tech_card__name", "assignment__id")
    autocomplete_fields = ("assignment", "tech_card", "production_stage")
    inlines = [ProductionDefectInline]
    actions = [conduct_assignment_items_action]

    @admin.display(description="Брак")
    def defect_quantity_display(self, obj):
        if not obj or not obj.pk:
            return "—"
        return obj.get_defect_quantity()

    @admin.display(description="Годная")
    def good_quantity_display(self, obj):
        if not obj or not obj.pk:
            return "—"
        return obj.good_quantity


@admin.register(ProductionDefect)
class ProductionDefectAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = ("id", "assignment_item", "product", "quantity", "comment_short", "created_at")
    list_filter = ("assignment_item__assignment",)
    search_fields = ("comment", "assignment_item__tech_card__name")
    autocomplete_fields = ("assignment_item", "product")

    @admin.display(description="Комментарий")
    def comment_short(self, obj):
        if not obj or not obj.comment:
            return "—"
        return obj.comment[:50] + "…" if len(obj.comment) > 50 else obj.comment


@admin.register(ProductionDeviation)
class ProductionDeviationAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = ("assignment", "assignment_item", "production_defect", "deviation_type", "material", "product", "quantity", "created_at")
    list_filter = ("deviation_type",)
    autocomplete_fields = ("assignment", "assignment_item", "material", "product")
    readonly_fields = ("production_defect",)


@admin.register(ProductionBatch)
class ProductionBatchAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = (
        "product",
        "order_item",
        "quantity_planned",
        "quantity_produced",
        "started_at",
        "finished_at",
    )
    list_filter = ("product",)
    search_fields = ("id", "product__name")


@admin.register(ProductionMaterialUsage)
class ProductionMaterialUsageAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = ("batch", "material", "quantity")
    list_filter = ("material",)


@admin.register(LaborTimeLog)
class LaborTimeLogAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = ("source_display", "employee", "operation_type", "minutes_spent", "date")
    list_filter = ("employee", "operation_type", "production_assignment")
    autocomplete_fields = ("batch", "production_assignment", "production_assignment_item", "employee", "operation_type")

    @admin.display(description="Партия / Задание")
    def source_display(self, obj):
        if obj.batch_id:
            return f"Партия #{obj.batch_id}"
        if obj.production_assignment_id:
            return f"Задание #{obj.production_assignment_id}" + (
                f" (этап {obj.production_assignment_item_id})" if obj.production_assignment_item_id else ""
            )
        return "—"

