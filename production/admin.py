# Регистрация моделей производства в разделе админки «Производство»
import re
from types import SimpleNamespace
# Порядок: Техкарты, Заказы на производство, Техоперации, Производственные задания,
# Выполнение этапов, Оплата труда, Техпроцессы, Этапы производства
from decimal import Decimal

from django import forms
from django.contrib import admin
from django.contrib.admin import RelatedOnlyFieldListFilter
from django.contrib.admin.widgets import RelatedFieldWidgetWrapper
from django.contrib import messages
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import path, reverse

from core.admin_mixins import ReturnToReferrerMixin
from core.admin import _material_average_unit_prices_map
from django.db.models import IntegerField, OuterRef, Prefetch, Q, Subquery

from django.forms.models import BaseInlineFormSet
from django.forms.utils import ErrorDict
from django.utils.html import format_html

from core.models import (
    LaborTimeLog,
    Material,
    MaterialGroup,
    Product,
    ProductLabor,
    ProductMaterial,
    ProductionAssignment,
    ProductionAssignmentItem,
    ProductionOrder,
    ProductionStage,
    TechCard,
    TechCardItem,
    TechCardLaborLine,
    TechOperation,
    TechOperationMaterial,
    TechOperationProduct,
    TechProcess,
    TechProcessStage,
)
from core.admin import (
    LaborTimeLogAdmin,
    ProductionAssignmentAdmin,
    ProductionAssignmentItemAdmin,
    ProductionBatchAdmin,
    ProductionOrderAdmin,
    ProductionStageAdmin,
    TechProcessAdmin,
)

from .models import (
    LaborTimeLogProxy,
    ProductionAssignmentItemProxy,
    ProductionAssignmentProxy,
    ProductionBatchProxy,
    ProductionOrderProxy,
    ProductionStageProxy,
    TechCardProxy,
    TechOperationProxy,
    TechProcessProxy,
)
from .techcard_changelist import (
    TechCardChangelist,
    build_techcard_sidebar_tree,
    tech_card_cut_cost_estimate,
    tech_card_material_cost_estimate,
)


def _tech_process_id_for_stages(request, parent):
    """ID техпроцесса для списка этапов в инлайнах: при POST — из формы; иначе с сохранённой карты."""
    if request.method == "POST":
        raw = request.POST.get("tech_process")
        if raw not in (None, ""):
            try:
                return int(raw)
            except (TypeError, ValueError):
                pass
    if parent is not None:
        tid = getattr(parent, "tech_process_id", None)
        if tid:
            return tid
    return None


class TechCardAdminForm(forms.ModelForm):
    """Подписи полей в стиле карточки «Технологическая карта»."""

    class Meta:
        model = TechCard
        fields = "__all__"
        exclude = ("labor_norm_input_unit",)
        labels = {
            "name": "Наименование",
            "description": "Комментарий",
            "product": "Изделие",
            "tech_process": "Техпроцесс",
            "card_group": "Группа техкарты",
            "allocate_cost": "Распределение стоимости",
            "production_stage": "Этап",
            "cut_length_meters_per_unit": "Норма реза, м на 1 изд.",
        }
        widgets = {
            "name": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].required = False
        self.fields["product"].required = True
        self.fields["product"].help_text = (
            "Выберите изделие из справочника товаров. Если его ещё нет, сначала создайте товар/изделие."
        )
        self.fields["tech_process"].required = True
        self.fields["tech_process"].help_text = (
            "<strong>Техпроцесс</strong><br>"
            "Техпроцесс — это маршрут изготовления изделия. "
            "Внутри техпроцесса задаются этапы, например: лазерная резка, шлифовка, покраска, упаковка."
        )
        self.fields["allocate_cost"].help_text = (
            "<strong>Распределение стоимости</strong><br>"
            "Используется в сложных техкартах, когда общую себестоимость нужно распределить между несколькими "
            "выходными изделиями или результатами производства. Для простой таблички, салфетницы или другого "
            "одного изделия поле можно оставить пустым."
        )

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get("product")
        if product:
            cleaned_data["name"] = product.name
        return cleaned_data


class TechCardLaborLineForm(forms.ModelForm):
    """Норма в строке хранится в нормо-часах; при выборе «минуты» на техкарте — ввод и перевод."""

    class Meta:
        model = TechCardLaborLine
        fields = "__all__"

    def __init__(self, *args, parent_tc=None, **kwargs):
        self._parent_tc = parent_tc
        super().__init__(*args, **kwargs)
        unit = TechCard.LABOR_NORM_INPUT_HOURS
        if parent_tc is not None:
            unit = getattr(
                parent_tc,
                "labor_norm_input_unit",
                TechCard.LABOR_NORM_INPUT_HOURS,
            ) or TechCard.LABOR_NORM_INPUT_HOURS
        self._norm_input_unit = unit
        nf = self.fields.get("norm_hours")
        if nf:
            nf.label = ""
            if unit == TechCard.LABOR_NORM_INPUT_MINUTES:
                nf.help_text = "Время станка/этапа в минутах; сохраняется как нормо-часы."
                if self.instance.pk and self.instance.norm_hours is not None:
                    mins = (self.instance.norm_hours * Decimal("60")).quantize(Decimal("0.0001"))
                    self.initial["norm_hours"] = mins
            else:
                nf.help_text = "Время станка/этапа в нормо-часах."

    def clean_norm_hours(self):
        v = self.cleaned_data.get("norm_hours")
        if v is None:
            return v
        if self._norm_input_unit == TechCard.LABOR_NORM_INPUT_MINUTES:
            return (v / Decimal("60")).quantize(Decimal("0.0001"))
        return v


# --- Техкарты ---
class TechCardItemInlineForm(forms.ModelForm):
    class Meta:
        model = TechCardItem
        fields = "__all__"
        widgets = {
            # Выбор комплектующего — только через поиск на вкладке «Продукция»; без Select2 в скрытой таблице.
            "product": forms.HiddenInput(),
            "composition_order": forms.HiddenInput(),
        }

    def _post_scalar(self, suffix: str) -> str:
        """Одно значение поля из POST (в т.ч. getlist — дубликаты ключей у Select2)."""
        if not self.is_bound:
            return ""
        key = f"{self.prefix}-{suffix}"
        raw = self.data.get(key)
        if raw is not None and str(raw).strip() != "":
            return str(raw).strip()
        getlist = getattr(self.data, "getlist", None)
        if callable(getlist):
            for v in getlist(key):
                if v is not None and str(v).strip() != "":
                    return str(v).strip()
        return ""

    def _raw_both_fk_empty(self):
        if not self.is_bound:
            return False
        return self._post_scalar("product") == "" and self._post_scalar("material") == ""

    def _raw_delete(self):
        if not self.is_bound:
            return False
        return self.data.get(self.prefix + "-DELETE") == "on"

    def _disposable_blank_new_row(self):
        return (
            self.is_bound
            and not self.instance.pk
            and not self._raw_delete()
            and self._raw_both_fk_empty()
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        f = self.fields.get("component_tech_card")
        if not f:
            return
        pid = getattr(self.instance, "product_id", None)
        if pid:
            f.queryset = TechCard.objects.filter(product_id=pid).order_by("name")
        else:
            f.queryset = TechCard.objects.none()

    def full_clean(self):
        # Новая строка без материала и без изделия (часто тип «комплектующие» без product):
        # has_changed() = True, поэтому не срабатывает empty_permitted — падают required-поля
        # до model _post_clean. Пропускаем валидацию полей; save_new_objects не сохраняет такую строку.
        if self.is_bound and self._disposable_blank_new_row():
            self._errors = ErrorDict(renderer=self.renderer)
            self.cleaned_data = {}
            return
        super().full_clean()


class TechCardItemFormSet(BaseInlineFormSet):
    """Не сохраняет пустую добавленную строку без материала и без изделия (часто «комплектующие» без product)."""

    def save_new(self, form, commit=True):
        if isinstance(form, TechCardItemInlineForm) and form._disposable_blank_new_row():
            return form.instance
        return super().save_new(form, commit=commit)

    def save_new_objects(self, commit=True):
        self.new_objects = []
        for form in self.extra_forms:
            if not form.has_changed():
                continue
            if self.can_delete and self._should_delete_form(form):
                continue
            skip_append = isinstance(form, TechCardItemInlineForm) and form._disposable_blank_new_row()
            obj = self.save_new(form, commit=commit)
            if skip_append:
                continue
            self.new_objects.append(obj)
            if not commit:
                self.saved_forms.append(form)
        return self.new_objects


class TechCardLaborLineFormSet(BaseInlineFormSet):
    """Строки «Деньги» — в порядке этапов техпроцесса, а не по алфавиту названия."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self._sort_forms_by_tech_process_order()

    def _sort_forms_by_tech_process_order(self):
        tc = self.instance
        if not tc or not getattr(tc, "tech_process_id", None):
            return
        stage_order = {
            tps.production_stage_id: tps.order
            for tps in tc.tech_process.get_stages_ordered()
        }

        def stage_id_for(form):
            if form.instance.production_stage_id:
                return form.instance.production_stage_id
            init = form.initial or {}
            val = init.get("production_stage")
            if val is None:
                return None
            return getattr(val, "pk", val)

        def is_template_row(form):
            return not form.instance.pk and stage_id_for(form) is None

        filled = []
        templates = []
        for form in self.forms:
            if is_template_row(form):
                templates.append(form)
            else:
                filled.append(form)

        filled.sort(
            key=lambda f: (
                stage_order.get(stage_id_for(f), 9999),
                f.instance.pk or 0,
            )
        )
        self.forms = filled + templates


class TechCardItemInline(admin.TabularInline):
    model = TechCardItem
    fk_name = "tech_card"
    form = TechCardItemInlineForm
    formset = TechCardItemFormSet
    extra = 0
    fields = (
        "production_stage",
        "item_kind",
        "material",
        "product",
        "quantity",
        "cut_length_meters_per_unit",
        "engrave_kind",
        "engrave_area_m2",
        "component_tech_card",
        "composition_order",
    )
    autocomplete_fields = ("material",)
    template = "admin/production/techcardproxy/techcarditem/tabular.html"
    ordering = ("item_kind", "composition_order", "pk")

    def get_formset(self, request, obj=None, **kwargs):
        self._parent_tech_card = obj
        return super().get_formset(request, obj, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "production_stage":
            tp_id = _tech_process_id_for_stages(
                request, getattr(self, "_parent_tech_card", None)
            )
            if tp_id:
                kwargs["queryset"] = (
                    ProductionStage.objects.filter(
                        techprocessstage__tech_process_id=tp_id
                    )
                    .order_by("techprocessstage__order", "name")
                    .distinct()
                )
            else:
                kwargs["queryset"] = ProductionStage.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "material",
            "product",
            "production_stage",
            "component_tech_card",
        )


class TechCardLaborLineInline(admin.TabularInline):
    model = TechCardLaborLine
    form = TechCardLaborLineForm
    formset = TechCardLaborLineFormSet
    extra = 0
    fields = (
        "production_stage",
        "hourly_rate_display",
        "norm_hours",
        "labor_pay_display",
        "employee_minutes",
        "employee_pay_display",
        "overhead_per_unit",
    )
    readonly_fields = (
        "hourly_rate_display",
        "labor_pay_display",
        "employee_pay_display",
    )
    template = "admin/production/techcardproxy/techcardlabor/tabular.html"
    classes = ["tc-labor-fieldset"]

    def get_formset(self, request, obj=None, **kwargs):
        self._parent_tech_card = obj
        parent_tc = obj
        missing_stage_ids = []
        if (
            obj
            and obj.pk
            and obj.tech_process_id
            and request.method in ("GET", "HEAD")
        ):
            existing_stage_ids = set(
                obj.labor_lines.values_list("production_stage_id", flat=True)
            )
            missing_stage_ids = [
                tps.production_stage_id
                for tps in obj.tech_process.get_stages_ordered()
                if tps.production_stage_id not in existing_stage_ids
            ]
            kwargs["extra"] = len(missing_stage_ids)
        if parent_tc is None:
            unit = TechCard.LABOR_NORM_INPUT_HOURS
            if request.method == "POST":
                u = request.POST.get("labor_norm_input_unit")
                if u in (TechCard.LABOR_NORM_INPUT_HOURS, TechCard.LABOR_NORM_INPUT_MINUTES):
                    unit = u
            parent_tc = SimpleNamespace(labor_norm_input_unit=unit)
        elif request.method == "POST":
            unit = request.POST.get("labor_norm_input_unit", TechCard.LABOR_NORM_INPUT_HOURS)
            if unit not in (TechCard.LABOR_NORM_INPUT_HOURS, TechCard.LABOR_NORM_INPUT_MINUTES):
                unit = TechCard.LABOR_NORM_INPUT_HOURS
            parent_tc = SimpleNamespace(labor_norm_input_unit=unit)

        class FormWithParent(TechCardLaborLineForm):
            def __init__(self, *a, **kw):
                kw["parent_tc"] = parent_tc
                super().__init__(*a, **kw)

        kwargs["form"] = FormWithParent
        formset = super().get_formset(request, obj, **kwargs)

        if not missing_stage_ids:
            return formset

        class FormSetWithMissingStages(formset):
            def __init__(self, *args, **formset_kwargs):
                if not formset_kwargs.get("data") and not formset_kwargs.get("files"):
                    formset_kwargs.setdefault(
                        "initial",
                        [
                            {
                                "production_stage": stage_id,
                                "norm_hours": Decimal("0"),
                                "employee_minutes": Decimal("0"),
                                "overhead_per_unit": Decimal("0"),
                            }
                            for stage_id in missing_stage_ids
                        ],
                    )
                super().__init__(*args, **formset_kwargs)

        return FormSetWithMissingStages

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "production_stage":
            tp_id = _tech_process_id_for_stages(
                request, getattr(self, "_parent_tech_card", None)
            )
            if tp_id:
                kwargs["queryset"] = (
                    ProductionStage.objects.filter(
                        techprocessstage__tech_process_id=tp_id
                    )
                    .order_by("techprocessstage__order", "name")
                    .distinct()
                )
            else:
                kwargs["queryset"] = ProductionStage.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("production_stage")
        parent = getattr(self, "_parent_tech_card", None)
        if parent and parent.tech_process_id:
            order_sq = TechProcessStage.objects.filter(
                tech_process_id=parent.tech_process_id,
                production_stage_id=OuterRef("production_stage_id"),
            ).values("order")[:1]
            return qs.annotate(
                _tp_stage_order=Subquery(order_sq, output_field=IntegerField())
            ).order_by("_tp_stage_order", "pk")
        return qs.order_by("production_stage__name", "pk")

    def hourly_rate_display(self, obj):
        if obj and obj.production_stage_id:
            r = obj.production_stage.hourly_rate
            if r is not None:
                rv = Decimal(str(r)).quantize(Decimal("0.01"))
                return format_html("{}&nbsp;&#8381;", format(rv, "f"))
        return "—"

    hourly_rate_display.short_description = "Стоимость нормо-часа"

    def labor_pay_display(self, obj):
        if not obj:
            return "—"
        if obj.production_stage_id and obj.norm_hours is not None:
            pay = obj.machine_pay_per_unit()
            return format_html("{}&nbsp;&#8381;", format(pay, "f"))
        return "—"

    labor_pay_display.short_description = "Станок/этап"

    def employee_hourly_rate_display(self, obj):
        if not obj or not obj.production_stage_id:
            return "—"
        rate = obj.employee_hourly_rate_for_plan()
        return format_html("{}&nbsp;&#8381;", format(rate.quantize(Decimal("0.01")), "f"))

    employee_hourly_rate_display.short_description = "Ставка сотрудника"

    def employee_pay_display(self, obj):
        if not obj:
            return "—"
        pay = obj.employee_pay_per_unit()
        return format_html("{}&nbsp;&#8381;", format(pay, "f"))

    employee_pay_display.short_description = "Сотрудник"


@admin.register(TechCardProxy)
class TechCardAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    form = TechCardAdminForm
    # Без дублирующей верхней панели (Сохранить / Удалить) — одна строка внизу формы
    save_on_top = False
    change_form_template = "admin/production/techcardproxy/change_form.html"
    change_list_template = "admin/production/techcardproxy/change_list.html"
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "product",
                    "name",
                    "tech_process",
                    "allocate_cost",
                    "description",
                ),
                "classes": ("tc-ms-main",),
            },
        ),
    )
    list_display = (
        "name",
        "total_cost_display",
        "material_cost_display",
        "labor_cost_display",
        "overhead_per_unit_display",
        "cut_cost_display",
        "comment_display",
    )
    list_filter = (("product", RelatedOnlyFieldListFilter),)
    search_fields = ("name", "description")
    search_help_text = "Наименование или комментарий"
    autocomplete_fields = ("product", "tech_process")
    inlines = [TechCardLaborLineInline, TechCardItemInline]
    # Оформление формы — Media; techcard_items_tabs.js подключается в tabular.html после TECHCARD_ITEMS_UI.

    def get_changelist(self, request, **kwargs):
        return TechCardChangelist

    def get_urls(self):
        info = self.model._meta.app_label, self.model._meta.model_name
        custom = [
            path(
                "tech-cards-for-product/<int:product_id>/",
                self.admin_site.admin_view(self.tech_cards_for_product_json),
                name="%s_%s_techcards_for_product" % info,
            ),
            path(
                "material-picker/groups/",
                self.admin_site.admin_view(self.material_picker_groups_json),
                name="%s_%s_material_picker_groups" % info,
            ),
            path(
                "material-picker/items/",
                self.admin_site.admin_view(self.material_picker_items_json),
                name="%s_%s_material_picker_items" % info,
            ),
        ]
        return custom + super().get_urls()

    def material_picker_groups_json(self, request):
        """Группы материалов для модального выбора в техкарте (как дерево в МойСклад)."""
        if not request.user.is_staff:
            return JsonResponse({"error": "forbidden"}, status=403)
        groups = [{"id": None, "name": "Все материалы"}]
        groups.extend(
            {"id": g.pk, "name": g.name}
            for g in MaterialGroup.objects.order_by("name")
        )
        return JsonResponse({"groups": groups})

    def material_picker_items_json(self, request):
        """Список материалов с пагинацией и фильтром по группе/поиску."""
        if not request.user.is_staff:
            return JsonResponse({"error": "forbidden"}, status=403)
        try:
            page = max(1, int(request.GET.get("page", 1)))
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = int(request.GET.get("page_size", 80))
        except (TypeError, ValueError):
            page_size = 80
        page_size = min(200, max(10, page_size))

        group = (request.GET.get("group") or "").strip()
        q = (request.GET.get("q") or "").strip()

        qs = Material.objects.select_related("group").all()
        if group in ("", "all"):
            pass
        elif group == "none":
            qs = qs.filter(group__isnull=True)
        else:
            try:
                qs = qs.filter(group_id=int(group))
            except (TypeError, ValueError):
                pass
        qs = qs.order_by("name")

        if q:
            tokens = [token.casefold() for token in re.split(r"\s+", q) if token.strip()]

            def material_matches(material):
                haystack = " ".join(
                    str(part or "")
                    for part in (
                        material.name,
                        material.material_type,
                        material.unit,
                        material.group.name if material.group_id else "",
                        material.thickness_mm,
                    )
                ).casefold()
                return all(token in haystack for token in tokens)

            rows = [m for m in qs if material_matches(m)]
            total = len(rows)
            start = (page - 1) * page_size
            slice_qs = rows[start : start + page_size]
        else:
            total = qs.count()
            start = (page - 1) * page_size
            slice_qs = qs[start : start + page_size]
        results = []
        for m in slice_qs:
            results.append(
                {
                    "id": m.pk,
                    "name": m.name,
                    "unit": (m.unit or "").strip(),
                    "stock": str(m.current_stock),
                    "material_type": (m.material_type or "").strip(),
                    "group_name": m.group.name if m.group_id else "",
                }
            )
        return JsonResponse(
            {
                "results": results,
                "page": page,
                "page_size": page_size,
                "total": total,
                "more": start + len(results) < total,
            }
        )

    def tech_cards_for_product_json(self, request, product_id):
        if not request.user.is_staff:
            return JsonResponse({"error": "forbidden"}, status=403)
        rows = list(
            TechCard.objects.filter(product_id=product_id)
            .order_by("name")
            .values("id", "name")
        )
        return JsonResponse(rows, safe=False)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "tech_process" and formfield is not None:
            w = formfield.widget
            if isinstance(w, RelatedFieldWidgetWrapper):
                w.can_change_related = False
                w.can_view_related = False
        return formfield

    class Media:
        # Django 6: css — только dict по типу носителя, не кортеж путей
        css = {"all": ("core/admin/techcard_change_form.css",)}
        js = ("core/admin/techcard_change_form.js",)

    @staticmethod
    def _tech_process_stages_map():
        """id техпроцесса (str) → [{id, name, hourly_rate, employee_hourly_rate}, …] в порядке этапов."""
        out = {}
        tps_qs = (
            TechProcessStage.objects.select_related("production_stage__master")
            .prefetch_related("production_stage__executors")
            .order_by("tech_process_id", "order", "production_stage__name")
        )
        by_tp = {}
        for tps in tps_qs:
            by_tp.setdefault(tps.tech_process_id, []).append(tps)
        for tp in TechProcess.objects.all():
            rows = []
            for tps in by_tp.get(tp.pk, []):
                st = tps.production_stage
                hr = st.hourly_rate
                emp_hr = st.employee_hourly_rate_for_plan()
                rows.append(
                    {
                        "id": st.pk,
                        "name": st.name,
                        "hourly_rate": "" if hr is None else format(hr, "f"),
                        "employee_hourly_rate": format(emp_hr, "f"),
                        "cut_rate_per_meter": (
                            ""
                            if st.cut_rate_per_meter is None
                            else format(st.cut_rate_per_meter, "f")
                        ),
                        "engrave_fill_rate_per_sq_m": (
                            ""
                            if st.engrave_fill_rate_per_sq_m is None
                            else format(st.engrave_fill_rate_per_sq_m, "f")
                        ),
                    }
                )
            out[str(tp.pk)] = rows
        return out

    def _techcard_form_extra_context(self, request, object_id=None):
        """Контекст формы техкарты: карта этапов и выбранная единица нормы (ч/м) для заголовка столбца."""
        extra = {
            "tech_process_stages_map": self._tech_process_stages_map(),
            "material_avg_unit_prices": _material_average_unit_prices_map(),
        }
        _stage_id_ph = "999999999"
        _change = reverse("admin:core_productionstage_change", args=[int(_stage_id_ph)])
        extra["production_stage_admin_urls"] = {
            "change": _change.replace(_stage_id_ph, "{id}") + "?_to_field=id&_popup=1",
            "delete": reverse("admin:core_productionstage_delete", args=[int(_stage_id_ph)]).replace(
                _stage_id_ph, "{id}"
            )
            + "?_to_field=id&_popup=1",
            "view": _change.replace(_stage_id_ph, "{id}") + "?_to_field=id",
            "add": reverse("admin:core_productionstage_add") + "?_to_field=id&_popup=1",
        }
        extra["techcard_title_product"] = ""
        extra["techcard_cost_breakdown"] = None
        obj = None
        if object_id not in (None, ""):
            try:
                obj = (
                    TechCard.objects.filter(pk=int(object_id))
                    .prefetch_related(
                        "items__material",
                        "items__product",
                        "items__component_tech_card",
                        "labor_lines__production_stage",
                    )
                    .first()
                )
            except (TypeError, ValueError):
                obj = None
        if obj and obj.pk:
            extra["techcard_cost_breakdown"] = {
                "materials": format(obj.planned_material_cost_per_unit(), "f"),
                "components": format(obj.planned_component_cost_per_unit(), "f"),
                "labor": format(obj.planned_labor_cost_per_unit(), "f"),
                "overhead": format(obj.planned_overhead_per_unit(), "f"),
                "cut": format(obj.planned_cut_cost_per_unit(), "f"),
                "total": format(obj.planned_total_cost_per_unit(), "f"),
            }
        if request.method == "POST":
            u = request.POST.get("labor_norm_input_unit")
            extra["labor_norm_input_unit_selected"] = (
                u
                if u in (TechCard.LABOR_NORM_INPUT_HOURS, TechCard.LABOR_NORM_INPUT_MINUTES)
                else TechCard.LABOR_NORM_INPUT_HOURS
            )
            product_id = request.POST.get("product")
            if product_id:
                extra["techcard_title_product"] = (
                    Product.objects.filter(pk=product_id).values_list("name", flat=True).first()
                    or ""
                )
        elif object_id:
            obj = self.get_object(request, object_id)
            extra["labor_norm_input_unit_selected"] = (
                (obj.labor_norm_input_unit or TechCard.LABOR_NORM_INPUT_HOURS)
                if obj
                else TechCard.LABOR_NORM_INPUT_HOURS
            )
            extra["techcard_title_product"] = obj.product.name if obj and obj.product_id else ""
        else:
            extra["labor_norm_input_unit_selected"] = TechCard.LABOR_NORM_INPUT_HOURS
            product_id = request.GET.get("product")
            if product_id:
                extra["techcard_title_product"] = (
                    Product.objects.filter(pk=product_id).values_list("name", flat=True).first()
                    or ""
                )
        return extra

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        pid = request.GET.get("product")
        if pid not in (None, ""):
            try:
                initial["product"] = int(pid)
            except (TypeError, ValueError):
                pass
        return initial

    def add_view(self, request, form_url="", extra_context=None):
        extra_context = {**(extra_context or {}), **self._techcard_form_extra_context(request, None)}
        return super().add_view(request, form_url, extra_context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = {**(extra_context or {}), **self._techcard_form_extra_context(request, object_id)}
        return super().change_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj, form, change):
        unit = request.POST.get("labor_norm_input_unit")
        if unit in (TechCard.LABOR_NORM_INPUT_HOURS, TechCard.LABOR_NORM_INPUT_MINUTES):
            obj.labor_norm_input_unit = unit
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related(
            "product",
            "product__product_group",
            "card_group",
            "tech_process",
        ).prefetch_related(
            Prefetch(
                "items",
                queryset=TechCardItem.objects.select_related(
                    "material",
                    "product",
                    "production_stage",
                    "component_tech_card",
                ),
            ),
            Prefetch(
                "labor_lines",
                queryset=TechCardLaborLine.objects.select_related("production_stage"),
            ),
            Prefetch(
                "product__labor_norms",
                queryset=ProductLabor.objects.select_related("operation_type"),
            ),
        )

    def changelist_view(self, request, extra_context=None):
        from urllib.parse import urlencode

        extra_context = extra_context or {}
        extra_context["techcard_sidebar"] = build_techcard_sidebar_tree()
        extra_context["tc_product_selected"] = request.GET.get("tc_product", "") or ""
        qcopy = request.GET.copy()
        qcopy.pop("tc_product", None)
        qcopy.pop("p", None)
        extra_context["tc_sidebar_qs_base"] = urlencode(qcopy, doseq=True)
        return super().changelist_view(request, extra_context)

    @admin.display(description="Себестоимость")
    def total_cost_display(self, obj):
        if not obj:
            return "—"
        cost = obj.planned_total_cost_per_unit()
        if cost == 0:
            return "—"
        return f"{cost} ₽"

    @admin.display(description="Оплата труда")
    def labor_cost_display(self, obj):
        if not obj:
            return "—"
        cost = obj.planned_labor_cost_per_unit()
        if cost == 0:
            return "—"
        return f"{cost} ₽"

    @admin.display(description="Материалы (оценка)")
    def material_cost_display(self, obj):
        if not obj:
            return "—"
        cost = tech_card_material_cost_estimate(obj)
        if cost == 0:
            return "—"
        return f"{cost} ₽"

    @admin.display(description="Затраты на пр-во")
    def overhead_per_unit_display(self, obj):
        if not obj:
            return "—"
        v = obj.planned_overhead_per_unit()
        if v == 0:
            return "—"
        return f"{v} ₽"

    @admin.display(description="Рез (план, ₽/изд.)")
    def cut_cost_display(self, obj):
        if not obj:
            return "—"
        cost = tech_card_cut_cost_estimate(obj)
        if cost == 0:
            return "—"
        return f"{cost} ₽"

    @admin.display(description="Комментарий")
    def comment_display(self, obj):
        if not obj or not obj.description:
            return "—"
        t = obj.description
        return t[:80] + "…" if len(t) > 80 else t

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        obj = form.instance
        if not obj.product_id:
            return
        obj.sync_material_norms_to_product()
        product = (
            Product.objects.prefetch_related(
                Prefetch(
                    "materials",
                    queryset=ProductMaterial.objects.select_related("material").order_by("pk"),
                ),
                Prefetch(
                    "labor_norms",
                    queryset=ProductLabor.objects.select_related("operation_type").order_by("pk"),
                ),
            ).get(pk=obj.product_id)
        )
        if product.product_kind == Product.PRODUCT_KIND_GOODS and product.apply_composed_goods_identity():
            product.save()


# --- Заказы на производство ---
@admin.register(ProductionOrderProxy)
class ProductionOrderAdminProxy(ProductionOrderAdmin):
    pass


# --- Производственные партии ---
@admin.register(ProductionBatchProxy)
class ProductionBatchAdminProxy(ProductionBatchAdmin):
    pass


# --- Техоперации ---
class TechOperationProductInline(admin.TabularInline):
    model = TechOperationProduct
    extra = 0
    autocomplete_fields = ("product",)


class TechOperationMaterialInline(admin.TabularInline):
    model = TechOperationMaterial
    extra = 0
    autocomplete_fields = ("material",)


@admin.action(description="Провести выбранные техоперации")
def conduct_tech_operations(modeladmin, request, queryset):
    errors = []
    conducted = 0
    for op in queryset.filter(status=TechOperation.STATUS_DRAFT):
        try:
            op.conduct()
            conducted += 1
        except ValueError as e:
            errors.append(f"№{op.pk}: {e}")
    if conducted:
        messages.success(request, f"Проведено техопераций: {conducted}.")
    if errors:
        messages.error(request, "Ошибки проведения: " + "; ".join(errors[:5]))


def _tech_op_admin_url(model, view, object_id=None):
    """URL имени для техоперации (учитывает прокси)."""
    app = model._meta.app_label
    name = model._meta.model_name
    if object_id is not None:
        return f"admin:{app}_{name}_{view}"
    return f"admin:{app}_{name}_{view}"


@admin.register(TechOperationProxy)
class TechOperationAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "date",
        "status",
        "product_warehouse",
        "material_warehouse",
        "tech_card",
        "production_order",
        "production_assignment_item",
        "production_cost",
        "get_total_cost_display",
        "created_at",
    )
    list_filter = ("status", "product_warehouse", "material_warehouse")
    search_fields = ("comment",)
    autocomplete_fields = (
        "organization",
        "product_warehouse",
        "material_warehouse",
        "tech_card",
        "production_order",
        "production_assignment_item",
    )
    inlines = [TechOperationProductInline, TechOperationMaterialInline]
    actions = [conduct_tech_operations]
    date_hierarchy = "date"
    readonly_fields = ("created_at",)
    change_form_template = "admin/production/techoperation/change_form.html"

    fieldsets = (
        (None, {
            "fields": (
                "organization",
                "product_warehouse",
                "material_warehouse",
                "tech_card",
                "production_order",
                "production_assignment_item",
                "status",
            ),
        }),
        ("Затраты и дата", {
            "fields": ("production_cost", "date", "comment", "created_at"),
        }),
    )

    def get_urls(self):
        urls = super().get_urls()
        app = self.model._meta.app_label
        name = self.model._meta.model_name
        custom = [
            path(
                "<int:object_id>/fill-from-tech-card/",
                self.admin_site.admin_view(self.fill_from_tech_card_view),
                name=f"{app}_{name}_fill_from_tech_card",
            ),
        ]
        return custom + urls

    def fill_from_tech_card_view(self, request, object_id):
        op = TechOperation.objects.get(pk=object_id)
        change_url = reverse(_tech_op_admin_url(self.model, "change"), args=[object_id])
        if not op.tech_card_id:
            messages.error(request, "У техоперации не указана техкарта.")
            return HttpResponseRedirect(change_url)
        if request.method == "POST":
            try:
                qty = Decimal(request.POST.get("production_quantity", "1").replace(",", "."))
            except Exception:
                qty = Decimal("1")
            if qty <= 0:
                qty = Decimal("1")
            op.fill_from_tech_card(qty)
            messages.success(request, f"Состав заполнен из техкарты при объёме производства {qty}.")
            return HttpResponseRedirect(change_url)
        return render(
            request,
            "admin/production/techoperation/fill_from_tech_card.html",
            {"op": op, "title": "Заполнить из техкарты"},
        )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        try:
            op = TechOperation.objects.get(pk=object_id)
            if op.tech_card_id:
                extra_context["fill_from_tech_card_url"] = reverse(
                    _tech_op_admin_url(self.model, "fill_from_tech_card"),
                    args=[object_id],
                )
        except TechOperation.DoesNotExist:
            pass
        return super().change_view(request, object_id, form_url, extra_context)

    @admin.display(description="Себестоимость")
    def get_total_cost_display(self, obj):
        if not obj or obj.pk is None:
            return "—"
        return f"{obj.get_total_cost()} ₽"


# --- Производственные задания ---
@admin.register(ProductionAssignmentProxy)
class ProductionAssignmentAdminProxy(ProductionAssignmentAdmin):
    change_list_template = "admin/production/productionassignmentproxy/change_list.html"


# --- Выполнение этапов ---
@admin.register(ProductionAssignmentItemProxy)
class ProductionAssignmentItemAdminProxy(ProductionAssignmentItemAdmin):
    pass


# --- Оплата труда ---
@admin.register(LaborTimeLogProxy)
class LaborTimeLogAdminProxy(LaborTimeLogAdmin):
    pass


# --- Техпроцессы ---
@admin.register(TechProcessProxy)
class TechProcessAdminProxy(TechProcessAdmin):
    pass


# --- Этапы производства ---
@admin.register(ProductionStageProxy)
class ProductionStageAdminProxy(ProductionStageAdmin):
    pass
