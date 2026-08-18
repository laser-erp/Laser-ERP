import json
from datetime import timedelta
from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.db.models import (
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce, Greatest, Least
from django.template.response import TemplateResponse
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone

from core.admin_mixins import ReturnToReferrerMixin
from core.models import Material, Order, OrderItem, Organization, Product
from core.services.fns import fetch_contragents
from core.services.production_stock_reports import pending_production_quantity_subquery

from .services.fanera_nest_receipt import build_nest_kits_payload
from .services.invoice_ocr import (
    apply_ocr_data_to_supplier_invoice,
    register_invoice_category_feedback,
    recognize_supplier_invoice,
)
from .models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseManagementProduct,
    ReceivedVatInvoice,
    SupplierInvoice,
    SupplierInvoiceCategoryMemory,
    SupplierPurchaseOrder,
    SupplierPurchaseOrderLine,
    SupplierReturn,
)


class SupplierOrganizationFKMixin:
    """Поле supplier — только контрагенты с ролью «Поставщик» (и текущее значение при правке)."""

    _supplier_fk_model = None

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "supplier" and self._supplier_fk_model is not None:
            q = Q(is_supplier=True)
            rm = getattr(request, "resolver_match", None)
            oid = rm.kwargs.get("object_id") if rm and rm.kwargs else None
            if oid:
                try:
                    sid = (
                        self._supplier_fk_model.objects.filter(pk=int(oid))
                        .values_list("supplier_id", flat=True)
                        .first()
                    )
                    if sid:
                        q |= Q(pk=sid)
                except (ValueError, TypeError):
                    pass
            kwargs["queryset"] = Organization.objects.filter(q).distinct().order_by("name")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


def _positive_decimal(value):
    if value is None or value == "":
        return None
    qty = Decimal(str(value).replace(",", "."))
    if qty <= 0:
        return None
    return qty


_GR_NUM_ATTRS = {"class": "vTextField laser-gr-num", "size": "8", "inputmode": "decimal", "autocomplete": "off"}


class GoodsReceiptLineForm(forms.ModelForm):
    """Строка приёмки: рулон/упаковка × содержимое и сумма — без ручного деления цены."""

    pack_count = forms.DecimalField(
        label="Упак.",
        required=False,
        localize=True,
        widget=forms.TextInput(attrs={**_GR_NUM_ATTRS, "size": "4", "placeholder": "1"}),
        help_text="Сколько рулонов, коробок или катушек пришло. Пусто = 1, если заполнено «В 1 упак.».",
    )
    qty_in_pack = forms.DecimalField(
        label="В 1 упак.",
        required=False,
        localize=True,
        widget=forms.TextInput(attrs={**_GR_NUM_ATTRS, "size": "6"}),
        help_text="Сколько единиц учёта в одной упаковке. Рулон 300 м при ед. «м» — 300. Кол-во = упак. × это число.",
    )

    class Meta:
        model = GoodsReceiptLine
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, label, help_text in (
            (
                "quantity",
                "Кол-во",
                "В единицах учёта материала (для стрейча — метры). Можно не считать: заполните «В 1 упак.».",
            ),
            (
                "unit_price",
                "Цена/ед.",
                "Цена за 1 ед. учёта (за метр, штуку). Если известна сумма за рулон — укажите сумму, цена посчитается сама.",
            ),
            (
                "amount",
                "Сумма",
                "Сумма по накладной за строку (цена рулона или партии). Кол-во + сумма → цена за ед. сама.",
            ),
        ):
            if name in self.fields:
                self.fields[name].required = False
                self.fields[name].label = label
                self.fields[name].help_text = help_text
                self.fields[name].widget.attrs.update(_GR_NUM_ATTRS)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("DELETE"):
            return cleaned
        if not cleaned.get("material") and not cleaned.get("product"):
            return cleaned
        pack_count = _positive_decimal(cleaned.get("pack_count"))
        qty_in_pack = _positive_decimal(cleaned.get("qty_in_pack"))
        if qty_in_pack is not None:
            if pack_count is None:
                pack_count = Decimal("1")
            cleaned["quantity"] = (pack_count * qty_in_pack).quantize(Decimal("0.0001"))
        qty = _positive_decimal(cleaned.get("quantity"))
        price = _positive_decimal(cleaned.get("unit_price"))
        amount = _positive_decimal(cleaned.get("amount"))
        if qty is not None and amount is not None and price is None:
            cleaned["unit_price"] = (amount / qty).quantize(Decimal("0.0001"))
            price = cleaned["unit_price"]
        elif qty is not None and price is not None:
            cleaned["amount"] = (qty * price).quantize(Decimal("0.01"))
        if cleaned.get("quantity") in (None, ""):
            self.add_error("quantity", "Укажите количество или «В 1 упак.» (и при необходимости «Упак.»).")
        if cleaned.get("unit_price") in (None, ""):
            self.add_error("unit_price", "Укажите цену за ед. или сумму строки.")
        return cleaned


class GoodsReceiptLineFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        inst = self.instance
        if getattr(inst, "status", None) != GoodsReceipt.STATUS_POSTED:
            return
        n = 0
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or not form.cleaned_data:
                continue
            if form.cleaned_data.get("DELETE"):
                continue
            if form.cleaned_data.get("material") or form.cleaned_data.get("product"):
                n += 1
        if n == 0:
            raise forms.ValidationError(
                "Для статуса «Проведён» нужна хотя бы одна строка с материалом или товаром и количеством."
            )


class GoodsReceiptLineInline(admin.TabularInline):
    model = GoodsReceiptLine
    form = GoodsReceiptLineForm
    formset = GoodsReceiptLineFormSet
    extra = 1
    autocomplete_fields = ("material", "product", "supplier_order_line")
    readonly_fields = ("unit_display",)
    fields = (
        "material",
        "unit_display",
        "quantity",
        "amount",
        "unit_price",
        "pack_count",
        "qty_in_pack",
        "product",
        "supplier_order_line",
    )
    template = "admin/procurement/goodsreceipt/edit_inline/tabular.html"

    @admin.display(description="Ед.")
    def unit_display(self, obj):
        if obj and obj.material_id:
            return (obj.material.unit or "").strip() or "—"
        if obj and obj.product_id:
            return (obj.product.unit or "").strip() or "—"
        return "—"


class SupplierPurchaseOrderLineInline(admin.TabularInline):
    model = SupplierPurchaseOrderLine
    extra = 1
    autocomplete_fields = ("product", "material")
    readonly_fields = ("quantity_received",)
    fields = ("product", "material", "quantity", "quantity_received", "unit_price")


@admin.register(SupplierPurchaseOrderLine)
class SupplierPurchaseOrderLineAdmin(admin.ModelAdmin):
    """Для автодополнения в строках приёмки; правка — через заказ поставщику."""

    search_fields = (
        "purchase_order__number",
        "product__name",
        "material__name",
    )
    list_display = ("purchase_order", "product", "material", "quantity", "quantity_received")

    def has_module_permission(self, request):
        return False


@admin.register(SupplierPurchaseOrder)
class SupplierPurchaseOrderAdmin(SupplierOrganizationFKMixin, ReturnToReferrerMixin, admin.ModelAdmin):
    _supplier_fk_model = SupplierPurchaseOrder
    list_display = ("number", "ordered_at", "supplier", "our_organization", "status", "comment_short")
    list_filter = ("status",)
    search_fields = ("number", "comment")
    autocomplete_fields = ("supplier", "our_organization")
    readonly_fields = ("number",)
    inlines = [SupplierPurchaseOrderLineInline]

    @admin.display(description="Назначение платежа")
    def comment_short(self, obj):
        if not obj or not obj.comment:
            return "—"
        t = obj.comment.strip()
        return t[:60] + "…" if len(t) > 60 else t


@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(SupplierOrganizationFKMixin, ReturnToReferrerMixin, admin.ModelAdmin):
    _supplier_fk_model = SupplierInvoice
    add_form_template = "admin/procurement/supplierinvoice/manual_change_form.html"
    change_form_template = "admin/procurement/supplierinvoice/change_form_1c.html"
    list_display = (
        "number",
        "invoice_date",
        "supplier",
        "our_organization",
        "total_amount",
        "expense_category",
        "ocr_status",
        "invoice_file_icon",
        "status",
        "comment_short",
    )
    list_filter = ("status", "ocr_status", "expense_category", "invoice_date")
    search_fields = ("number", "comment")
    autocomplete_fields = ("supplier", "our_organization")
    readonly_fields = (
        "number",
        "ocr_status",
        "ocr_reviewed_at",
        "ocr_data_pretty",
        "ocr_result_preview",
    )
    fieldsets = (
        ("Документ", {"fields": ("number", "invoice_date", "status", "expense_category")}),
        ("Контрагенты", {"fields": ("supplier", "our_organization")}),
        ("Финансы", {"fields": ("total_amount", "comment")}),
        ("Файл счёта", {"fields": ("invoice_file",)}),
        (
            "OCR и разбор",
            {
                "fields": ("ocr_status", "ocr_reviewed_at", "ocr_data_pretty", "ocr_result_preview"),
                "classes": ("collapse",),
                "description": "Технический блок распознавания (для проверки и отладки).",
            },
        ),
    )
    actions = ["run_invoice_ocr", "apply_invoice_ocr_draft"]

    @staticmethod
    def _normalized_digits(value: str) -> str:
        return "".join(ch for ch in str(value or "") if ch.isdigit())

    @staticmethod
    def _normalized_text(value: str) -> str:
        return str(value or "").strip()

    def _find_organization_by_inn_kpp(self, inn_digits: str, kpp_digits: str = ""):
        if not inn_digits:
            return None
        inn_matches = []
        for org in Organization.objects.all().only("id", "inn", "kpp", "is_supplier").order_by("id"):
            if self._normalized_digits(org.inn) != inn_digits:
                continue
            inn_matches.append(org)
            if kpp_digits and self._normalized_digits(org.kpp) == kpp_digits:
                return org
        if inn_matches:
            return inn_matches[0]
        return None

    def _ensure_supplier_from_ocr_inn(self, request, invoice) -> None:
        data = invoice.ocr_data or {}
        supplier_inn = self._normalized_digits(data.get("supplier_inn") or "")
        supplier_kpp = self._normalized_digits(data.get("supplier_kpp") or "")
        if len(supplier_inn) not in (10, 12):
            return

        org = self._find_organization_by_inn_kpp(supplier_inn, supplier_kpp)
        if org:
            changed = False
            if not org.is_supplier:
                org.is_supplier = True
                changed = True
            if changed:
                org.save(update_fields=["is_supplier"])
            if invoice.supplier_id != org.pk:
                invoice.supplier = org
                invoice.save(update_fields=["supplier"])
            return

        try:
            found = fetch_contragents(supplier_inn)
        except Exception as exc:  # noqa: BLE001
            messages.warning(
                request,
                f"Не удалось создать контрагента по распознанному ИНН {supplier_inn}: {exc}",
            )
            return

        if not found:
            messages.warning(
                request,
                f"По распознанному ИНН {supplier_inn} контрагент не найден в базе ФНС.",
            )
            return

        payload = next(
            (
                row
                for row in found
                if self._normalized_digits(row.get("inn")) == supplier_inn
            ),
            found[0],
        )
        payload_inn = self._normalized_digits(payload.get("inn") or supplier_inn)
        payload_kpp = self._normalized_digits(payload.get("kpp") or "")
        org = self._find_organization_by_inn_kpp(payload_inn, payload_kpp)
        if org:
            update_fields = []
            if not org.is_supplier:
                org.is_supplier = True
                update_fields.append("is_supplier")
            if payload_kpp and not self._normalized_digits(org.kpp):
                org.kpp = self._normalized_text(payload.get("kpp"))
                update_fields.append("kpp")
            if self._normalized_text(payload.get("ogrn")) and not self._normalized_text(org.ogrn):
                org.ogrn = self._normalized_text(payload.get("ogrn"))
                update_fields.append("ogrn")
            if self._normalized_text(payload.get("legal_address")) and not self._normalized_text(org.legal_address):
                org.legal_address = self._normalized_text(payload.get("legal_address"))
                update_fields.append("legal_address")
            if update_fields:
                org.save(update_fields=update_fields)
            if invoice.supplier_id != org.pk:
                invoice.supplier = org
                invoice.save(update_fields=["supplier"])
            messages.info(
                request,
                f"Найден существующий контрагент по ИНН/КПП: {org.name}. Дубль не создан.",
            )
            return

        org = Organization.objects.create(
            name=self._normalized_text(payload.get("name")) or "Новый контрагент",
            inn=self._normalized_text(payload.get("inn")),
            kpp=self._normalized_text(payload.get("kpp")),
            ogrn=self._normalized_text(payload.get("ogrn")),
            legal_address=self._normalized_text(payload.get("legal_address")),
            is_individual=bool(payload.get("is_individual")),
            is_supplier=True,
            is_buyer=True,
        )
        invoice.supplier = org
        invoice.save(update_fields=["supplier"])
        messages.success(
            request,
            f"Контрагент по ИНН {supplier_inn} создан автоматически: {org.name}.",
        )

    def _supplier_invoice_choice_context(self, request):
        opts = self.model._meta
        return {
            **self.admin_site.each_context(request),
            "opts": opts,
            "title": "Добавить счёт поставщика",
            "manual_add_url": f"{request.path}?mode=manual",
            "changelist_url": reverse("admin:procurement_supplierinvoice_changelist"),
        }

    def _create_invoice_from_ocr_upload(self, request):
        uploaded_file = request.FILES.get("invoice_file")
        if not uploaded_file:
            messages.error(request, "Выберите файл счёта для распознавания.")
            return HttpResponseRedirect(request.path)

        supplier = Organization.objects.filter(is_supplier=True).order_by("name").first()
        if not supplier:
            supplier = Organization.objects.order_by("name").first()
        if not supplier:
            supplier = Organization.objects.create(
                name="Поставщик (временный)",
                is_supplier=True,
                is_buyer=True,
            )
            messages.info(
                request,
                "Создан временный поставщик. После OCR будет выполнена проверка по ИНН и подстановка контрагента.",
            )

        invoice = SupplierInvoice(supplier=supplier, status=SupplierInvoice.STATUS_DRAFT)
        buyer_only = list(Organization.objects.filter(is_buyer=True).order_by("name")[:2])
        if len(buyer_only) == 1:
            invoice.our_organization = buyer_only[0]
        invoice.invoice_file = uploaded_file
        invoice.save()

        recognize_supplier_invoice(invoice)
        invoice.refresh_from_db(fields=["ocr_data", "ocr_status"])
        self._ensure_supplier_from_ocr_inn(request, invoice)
        changed_fields = apply_ocr_data_to_supplier_invoice(invoice)
        if changed_fields:
            messages.success(
                request,
                "Счёт создан и автоматически заполнен по файлу: "
                + ", ".join(changed_fields[:5]),
            )
        else:
            messages.warning(
                request,
                "Счёт создан, но часть полей не определилась автоматически. Проверьте карточку вручную.",
            )
        if not (invoice.expense_category or "").strip():
            messages.warning(
                request,
                "Выберите категорию расхода и сохраните счёт. "
                "После 3 одинаковых подтверждений по такому наименованию категория будет подставляться автоматически.",
            )
        change_url = reverse("admin:procurement_supplierinvoice_change", args=[invoice.pk])
        return HttpResponseRedirect(change_url)

    def add_view(self, request, form_url="", extra_context=None):
        entry_mode = (request.POST.get("_entry_mode") or request.GET.get("mode") or "").strip()
        if request.method == "POST" and entry_mode == "ocr_upload":
            return self._create_invoice_from_ocr_upload(request)
        if request.method == "GET" and entry_mode != "manual":
            context = self._supplier_invoice_choice_context(request)
            return TemplateResponse(
                request,
                "admin/procurement/supplierinvoice/add_entry_choice.html",
                context,
            )
        extra = dict(extra_context or {})
        extra["show_entry_back"] = True
        extra["entry_choice_url"] = request.path
        return super().add_view(request, form_url=form_url, extra_context=extra)

    @admin.action(description="Запустить OCR по файлу счёта")
    def run_invoice_ocr(self, request, queryset):
        done = 0
        autofilled = 0
        need_category = 0
        for inv in queryset:
            recognize_supplier_invoice(inv)
            inv.refresh_from_db(fields=["ocr_data", "ocr_status", "comment", "expense_category"])
            changed_fields = apply_ocr_data_to_supplier_invoice(inv)
            if changed_fields:
                autofilled += 1
            if not (inv.expense_category or "").strip():
                need_category += 1
            done += 1
        if done:
            messages.success(
                request,
                f"OCR выполнен для счетов: {done}. Автозаполнение применено: {autofilled}.",
            )
        if need_category:
            messages.warning(
                request,
                f"Для {need_category} счет(ов) выберите категорию вручную. "
                "После 3 подтверждений по одинаковому наименованию категория станет автоматической.",
            )

    @admin.action(description="Подтвердить OCR-черновик и заполнить поля счёта")
    def apply_invoice_ocr_draft(self, request, queryset):
        applied = 0
        for inv in queryset:
            changed_fields = apply_ocr_data_to_supplier_invoice(inv)
            if changed_fields:
                applied += 1
        if applied:
            messages.success(request, f"OCR-черновик подтвержден для счетов: {applied}.")

    @admin.display(description="Комментарий")
    def comment_short(self, obj):
        if not obj or not obj.comment:
            return "—"
        t = obj.comment.strip()
        return t[:60] + "…" if len(t) > 60 else t

    @admin.display(description="Файл счёта")
    def invoice_file_icon(self, obj):
        if not obj or not obj.invoice_file:
            return "—"
        return format_html(
            '<a href="{}" target="_blank" title="Открыть файл счёта" aria-label="Открыть файл счёта" '
            'style="text-decoration:none;font-size:18px;line-height:1">🧾</a>',
            obj.invoice_file.url,
        )

    def save_model(self, request, obj, form, change):
        if request.POST.get("_conduct_close") == "1":
            obj.status = SupplierInvoice.STATUS_APPROVED
        prev_file_name = None
        if change and obj.pk:
            prev = SupplierInvoice.objects.filter(pk=obj.pk).only("invoice_file").first()
            prev_file_name = prev.invoice_file.name if prev and prev.invoice_file else ""
        super().save_model(request, obj, form, change)
        new_file_name = obj.invoice_file.name if obj.invoice_file else ""
        file_changed = bool(new_file_name) and new_file_name != (prev_file_name or "")
        needs_ocr_retry = bool(new_file_name) and (
            not obj.ocr_data or obj.ocr_status in {SupplierInvoice.OCR_PENDING, SupplierInvoice.OCR_FAILED}
        )
        needs_apply_retry = bool(new_file_name) and (
            bool(obj.ocr_data)
            and (not (obj.comment or "").strip() or not (obj.expense_category or "").strip())
        )
        if file_changed or needs_ocr_retry:
            recognize_supplier_invoice(obj)
            obj.refresh_from_db(fields=["ocr_data", "ocr_status"])
            self._ensure_supplier_from_ocr_inn(request, obj)
            changed_fields = apply_ocr_data_to_supplier_invoice(obj)
            if changed_fields:
                messages.success(
                    request,
                    "Счёт распознан и поля автоматически заполнены: "
                    + ", ".join(changed_fields[:4]),
                )
            elif obj.ocr_status == SupplierInvoice.OCR_FAILED:
                messages.warning(request, "Файл загружен, но OCR не смог заполнить поля автоматически.")
        elif needs_apply_retry:
            changed_fields = apply_ocr_data_to_supplier_invoice(obj)
            if changed_fields:
                messages.success(
                    request,
                    "Поля счёта дополнительно заполнены из OCR: " + ", ".join(changed_fields[:4]),
                )
        if not (obj.expense_category or "").strip() and (obj.comment or "").strip():
            messages.warning(
                request,
                "Категория расхода пока не определена автоматически. "
                "Выберите её вручную — система запомнит выбор и после 3 совпадений начнёт подставлять сама.",
            )
        confirmations, auto_ready = register_invoice_category_feedback(obj)
        if confirmations:
            if auto_ready:
                messages.success(
                    request,
                    f"Категория запомнена ({confirmations}/3+). "
                    "Для такого же наименования будет автоподстановка.",
                )
            else:
                messages.info(
                    request,
                    f"Выбор категории запомнен ({confirmations}/3). "
                    "После 3 подтверждений включится автоподстановка.",
                )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        obj = self.get_object(request, object_id)
        if request.method == "GET" and obj and obj.invoice_file:
            needs_fill = (
                (obj.number or "").startswith("СП-")
                or not (obj.comment or "").strip()
                or not (obj.expense_category or "").strip()
                or not (obj.ocr_data or {})
            )
            if needs_fill:
                if not obj.ocr_data or obj.ocr_status in {
                    SupplierInvoice.OCR_PENDING,
                    SupplierInvoice.OCR_FAILED,
                }:
                    recognize_supplier_invoice(obj)
                    obj.refresh_from_db(fields=["ocr_data", "ocr_status"])
                changed_fields = apply_ocr_data_to_supplier_invoice(obj)
                if changed_fields:
                    messages.info(
                        request,
                        "Карточка автоматически дополнена по OCR: "
                        + ", ".join(changed_fields[:5]),
                    )
        return super().change_view(request, object_id, form_url=form_url, extra_context=extra_context)

    @admin.display(description="OCR: распознанные поля")
    def ocr_data_pretty(self, obj):
        if not obj or not obj.ocr_data:
            return "—"
        data_text = json.dumps(obj.ocr_data, ensure_ascii=False, indent=2)
        return format_html(
            '<pre style="max-height:220px;overflow:auto;white-space:pre-wrap;margin:0">{}</pre>',
            data_text,
        )

    @admin.display(description="OCR: исходный текст")
    def ocr_result_preview(self, obj):
        text = (obj.ocr_result_text or "").strip()
        if not text:
            return "—"
        return format_html(
            '<pre style="max-height:300px;overflow:auto;white-space:pre-wrap;margin:0">{}</pre>',
            text,
        )


@admin.register(SupplierInvoiceCategoryMemory)
class SupplierInvoiceCategoryMemoryAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    list_display = (
        "source_name_short",
        "category",
        "confirmations",
        "is_auto_ready_flag",
        "updated_at",
    )
    list_filter = ("category", "confirmations", "updated_at")
    search_fields = ("source_name", "normalized_name")
    readonly_fields = ("normalized_name", "created_at", "updated_at")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "source_name",
                    "normalized_name",
                    "category",
                    "confirmations",
                )
            },
        ),
        ("Служебное", {"fields": ("created_at", "updated_at")}),
    )
    actions = [
        "mark_auto_ready",
        "decrease_to_learning",
        "increase_confirmations",
        "reset_confirmations",
    ]

    @admin.action(description="Сделать автоподстановку (подтверждений = 3)")
    def mark_auto_ready(self, request, queryset):
        updated = queryset.update(confirmations=3)
        if updated:
            messages.success(request, f"Автоподстановка включена для правил: {updated}.")

    @admin.action(description="Вернуть в режим обучения (подтверждений = 1)")
    def decrease_to_learning(self, request, queryset):
        updated = queryset.update(confirmations=1)
        if updated:
            messages.info(request, f"Переведено в режим обучения: {updated}.")

    @admin.action(description="Добавить +1 подтверждение")
    def increase_confirmations(self, request, queryset):
        updated = 0
        for obj in queryset:
            obj.confirmations += 1
            obj.save(update_fields=["confirmations", "updated_at"])
            updated += 1
        if updated:
            messages.success(request, f"Подтверждения увеличены для правил: {updated}.")

    @admin.action(description="Сбросить подтверждения в 0")
    def reset_confirmations(self, request, queryset):
        updated = queryset.update(confirmations=0)
        if updated:
            messages.warning(
                request,
                f"Подтверждения сброшены для правил: {updated}. Правила не будут автоприменяться.",
            )

    @admin.display(description="Наименование")
    def source_name_short(self, obj):
        text = (obj.source_name or "").strip()
        if not text:
            return "—"
        return text[:90] + "…" if len(text) > 90 else text

    @admin.display(description="Авто", boolean=True)
    def is_auto_ready_flag(self, obj):
        return obj.is_auto_ready


@admin.register(GoodsReceipt)
class GoodsReceiptAdmin(SupplierOrganizationFKMixin, ReturnToReferrerMixin, admin.ModelAdmin):
    _supplier_fk_model = GoodsReceipt
    change_form_template = "admin/procurement/goodsreceipt/change_form.html"
    list_display = (
        "number",
        "received_at",
        "warehouse",
        "supplier",
        "our_organization",
        "contract_ref",
        "total_amount",
        "paid_amount",
        "incoming_document_date",
        "incoming_number",
        "status",
        "posted_at",
        "is_sent",
        "is_printed",
        "comment_short",
    )
    list_filter = ("status", "warehouse", "is_sent", "is_printed", "received_at")
    search_fields = ("number", "incoming_number", "comment")
    autocomplete_fields = ("warehouse", "supplier", "our_organization", "contract_ref")
    readonly_fields = ("number", "total_amount", "posted_at")
    date_hierarchy = "received_at"
    inlines = [GoodsReceiptLineInline]
    fieldsets = (
        (
            None,
            {
                "classes": ("gr-main-fields",),
                "fields": (
                    "warehouse",
                    "supplier",
                    "contract_ref",
                    "received_at",
                    "status",
                    "total_amount",
                ),
            },
        ),
        (
            "Документ поставщика",
            {
                "classes": ("collapse",),
                "fields": (
                    "our_organization",
                    "incoming_number",
                    "incoming_document_date",
                    "paid_amount",
                    "comment",
                ),
            },
        ),
        (
            "Служебное",
            {
                "classes": ("collapse",),
                "fields": ("number", "posted_at"),
            },
        ),
    )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        obj = form.instance
        obj.recalc_total_from_lines()
        GoodsReceipt.objects.filter(pk=obj.pk).update(total_amount=obj.total_amount)
        obj.refresh_from_db()
        if obj.status == GoodsReceipt.STATUS_POSTED and not obj.posted_at:
            obj.conduct()
            obj.refresh_from_db()

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj and obj.posted_at:
            for f in self.model._meta.fields:
                if not f.editable:
                    continue
                if f.name == "comment":
                    continue
                if f.name not in ro:
                    ro.append(f.name)
        return ro

    def get_inlines(self, request, obj):
        if obj and obj.posted_at:
            return []
        return [GoodsReceiptLineInline]

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["goods_receipt_unit_map"] = {
            "materials": {
                str(m.pk): (m.unit or "").strip()
                for m in Material.objects.only("pk", "unit").order_by("pk")
            },
            "products": {
                str(p.pk): (p.unit or "").strip()
                for p in Product.objects.filter(product_kind=Product.PRODUCT_KIND_GOODS)
                .only("pk", "unit")
                .order_by("pk")
            },
        }
        extra_context["fanera_nest_kits_json"] = build_nest_kits_payload()
        return super().changeform_view(request, object_id, form_url, extra_context)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj)

    @admin.display(description="Комментарий")
    def comment_short(self, obj):
        if not obj or not obj.comment:
            return "—"
        t = obj.comment.strip()
        return t[:60] + "…" if len(t) > 60 else t


@admin.register(SupplierReturn)
class SupplierReturnAdmin(SupplierOrganizationFKMixin, ReturnToReferrerMixin, admin.ModelAdmin):
    _supplier_fk_model = SupplierReturn
    list_display = (
        "number",
        "returned_at",
        "supplier",
        "warehouse",
        "total_amount",
        "status",
        "comment_short",
    )
    list_filter = ("status",)
    search_fields = ("number", "comment")
    autocomplete_fields = ("supplier", "warehouse")
    readonly_fields = ("number",)

    @admin.display(description="Комментарий")
    def comment_short(self, obj):
        if not obj or not obj.comment:
            return "—"
        t = obj.comment.strip()
        return t[:60] + "…" if len(t) > 60 else t


@admin.register(ReceivedVatInvoice)
class ReceivedVatInvoiceAdmin(SupplierOrganizationFKMixin, ReturnToReferrerMixin, admin.ModelAdmin):
    _supplier_fk_model = ReceivedVatInvoice
    list_display = (
        "number",
        "invoice_date",
        "supplier",
        "our_organization",
        "total_amount",
        "status",
        "comment_short",
    )
    list_filter = ("status", "invoice_date")
    search_fields = ("number", "comment")
    autocomplete_fields = ("supplier", "our_organization")
    readonly_fields = ("number",)

    @admin.display(description="Комментарий")
    def comment_short(self, obj):
        if not obj or not obj.comment:
            return "—"
        t = obj.comment.strip()
        return t[:60] + "…" if len(t) > 60 else t


@admin.register(PurchaseManagementProduct)
class PurchaseManagementProductAdmin(ReturnToReferrerMixin, admin.ModelAdmin):
    """
    Остатки, открытые заказы покупателей, заказы поставщикам и плановый выпуск (ожидание), продажи за 30 дней.
    Резерв = min(открытый спрос, остаток) — сколько со склада покрывает текущие заказы.
    Доступно = остаток − резерв.
    Ожидание (поставщик) = сумма непоставленного по строкам заказов поставщику: max(0, заказано − получено)
    (статусы «Отправлен», «Подтверждён»).
    Ожидание (производство) = сумма max(0, план − годная) по заданиям с флажком «Ожидание»
    (статусы «Черновик», «В работе»).
    Дней на складе = остаток / средние продажи (без заказов и поставок).
    Дней запаса = max(0, остаток + ожидание поставщика + ожидание производства − открытые заказы) / средние продажи.
    """

    _OPEN_ORDER_STATUSES = (Order.STATUS_NEW, Order.STATUS_IN_PROGRESS)

    list_display = (
        "name",
        "db_code",
        "article",
        "unit",
        "col_quantity",
        "col_sum",
        "col_cost",
        "col_profit",
        "col_margin",
        "col_sales_per_day",
        "col_stock",
        "col_reserved",
        "col_pending",
        "col_prod_pending",
        "col_available",
        "col_days_wh",
        "col_days_supply",
        "col_supply",
    )
    list_filter = ("product_kind", "unit")
    search_fields = ("name", "article", "code")
    ordering = ("name",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        open_st = self._OPEN_ORDER_STATUSES
        open_qty_sq = Subquery(
            OrderItem.objects.filter(
                product_id=OuterRef("pk"),
                order__status__in=open_st,
            )
            .values("product_id")
            .annotate(t=Sum("quantity"))
            .values("t")[:1],
            output_field=DecimalField(max_digits=16, decimal_places=3),
        )
        open_val_sq = Subquery(
            OrderItem.objects.filter(
                product_id=OuterRef("pk"),
                order__status__in=open_st,
            )
            .annotate(
                lv=ExpressionWrapper(
                    F("quantity")
                    * Coalesce(
                        F("planned_price"),
                        F("product__planned_price"),
                        Value(Decimal("0")),
                    ),
                    output_field=DecimalField(max_digits=18, decimal_places=2),
                )
            )
            .values("product_id")
            .annotate(s=Sum("lv"))
            .values("s")[:1],
            output_field=DecimalField(max_digits=18, decimal_places=2),
        )
        cut = timezone.now() - timedelta(days=30)
        sold_30_sq = Subquery(
            OrderItem.objects.filter(
                product_id=OuterRef("pk"),
                order__status=Order.STATUS_DONE,
                order__created_at__gte=cut,
            )
            .values("product_id")
            .annotate(t=Sum("quantity"))
            .values("t")[:1],
            output_field=DecimalField(max_digits=16, decimal_places=3),
        )
        po_pending_sq = Subquery(
            SupplierPurchaseOrderLine.objects.filter(
                product_id=OuterRef("pk"),
                purchase_order__status__in=SupplierPurchaseOrder.INCOMING_STATUSES,
            )
            .annotate(
                _line_pending=Greatest(
                    F("quantity")
                    - Coalesce(F("quantity_received"), Value(Decimal("0"))),
                    Value(Decimal("0")),
                    output_field=DecimalField(max_digits=16, decimal_places=3),
                )
            )
            .values("product_id")
            .annotate(t=Sum("_line_pending"))
            .values("t")[:1],
            output_field=DecimalField(max_digits=16, decimal_places=3),
        )
        dec3 = DecimalField(max_digits=16, decimal_places=3)
        qs = (
            super()
            .get_queryset(request)
            .filter(product_kind=Product.PRODUCT_KIND_GOODS)
            .annotate(
                _stock_total=Coalesce(
                    Sum("warehouse_stocks__quantity"),
                    Value(Decimal("0")),
                    output_field=dec3,
                ),
                _open_qty=Coalesce(
                    open_qty_sq,
                    Value(Decimal("0")),
                    output_field=dec3,
                ),
                _open_val=Coalesce(
                    open_val_sq,
                    Value(Decimal("0")),
                    output_field=DecimalField(max_digits=18, decimal_places=2),
                ),
                _sold_30=Coalesce(
                    sold_30_sq,
                    Value(Decimal("0")),
                    output_field=dec3,
                ),
                _po_pending=Coalesce(
                    po_pending_sq,
                    Value(Decimal("0")),
                    output_field=dec3,
                ),
                _prod_pending=Coalesce(
                    pending_production_quantity_subquery(),
                    Value(Decimal("0")),
                    output_field=dec3,
                ),
            )
            .annotate(
                _reserved_physical=Least(
                    F("_open_qty"),
                    F("_stock_total"),
                    output_field=dec3,
                ),
            )
            .annotate(
                _available_calc=Greatest(
                    F("_stock_total") - F("_reserved_physical"),
                    Value(Decimal("0")),
                    output_field=dec3,
                ),
            )
            .annotate(
                _coverage_for_days=Greatest(
                    F("_stock_total") + F("_po_pending") + F("_prod_pending") - F("_open_qty"),
                    Value(Decimal("0")),
                    output_field=dec3,
                ),
            )
        )
        return qs

    @admin.display(description="Код")
    def db_code(self, obj):
        return obj.pk

    @admin.display(description="Кол-во (открытые заказы клиентов)", ordering="_open_qty")
    def col_quantity(self, obj):
        return self._fmt_qty(getattr(obj, "_open_qty", None))

    @admin.display(description="Сумма", ordering="_open_val")
    def col_sum(self, obj):
        return self._fmt_money(getattr(obj, "_open_val", None))

    @admin.display(description="Себестоимость (по открытым заказам)")
    def col_cost(self, obj):
        oq = getattr(obj, "_open_qty", None) or Decimal("0")
        if obj.purchase_price is None or oq == 0:
            return "—"
        return self._fmt_money((oq * obj.purchase_price).quantize(Decimal("0.01")))

    @admin.display(description="Прибыль (по открытым заказам)")
    def col_profit(self, obj):
        ov = getattr(obj, "_open_val", None)
        oq = getattr(obj, "_open_qty", None) or Decimal("0")
        if ov is None or obj.purchase_price is None:
            return "—"
        cost = (oq * obj.purchase_price).quantize(Decimal("0.01"))
        return self._fmt_money((ov - cost).quantize(Decimal("0.01")))

    @admin.display(description="Рентабельность %")
    def col_margin(self, obj):
        ov = getattr(obj, "_open_val", None)
        oq = getattr(obj, "_open_qty", None) or Decimal("0")
        if ov is None or obj.purchase_price is None or ov == 0:
            return "—"
        cost = (oq * obj.purchase_price).quantize(Decimal("0.01"))
        p = ov - cost
        return f"{(p / ov * Decimal('100')).quantize(Decimal('0.1'))} %"

    @admin.display(description="Продаж в день (30 дн.)", ordering="_sold_30")
    def col_sales_per_day(self, obj):
        s30 = getattr(obj, "_sold_30", None)
        if s30 is None:
            return "—"
        per = (s30 / Decimal("30")).quantize(Decimal("0.001"))
        return self._fmt_qty(per)

    @admin.display(description="Остаток", ordering="_stock_total")
    def col_stock(self, obj):
        return self._fmt_qty(getattr(obj, "_stock_total", None))

    @admin.display(description="Резерв (под открытые заказы)", ordering="_reserved_physical")
    def col_reserved(self, obj):
        return self._fmt_qty(getattr(obj, "_reserved_physical", None))

    @admin.display(description="Ожидание (заказ у поставщика)", ordering="_po_pending")
    def col_pending(self, obj):
        return self._fmt_qty(getattr(obj, "_po_pending", None))

    @admin.display(description="Ожидание (производство)", ordering="_prod_pending")
    def col_prod_pending(self, obj):
        return self._fmt_qty(getattr(obj, "_prod_pending", None))

    @admin.display(description="Доступно", ordering="_available_calc")
    def col_available(self, obj):
        return self._fmt_qty(getattr(obj, "_available_calc", None))

    @admin.display(description="Дней на складе")
    def col_days_wh(self, obj):
        st = getattr(obj, "_stock_total", None) or Decimal("0")
        s30 = getattr(obj, "_sold_30", None) or Decimal("0")
        per = s30 / Decimal("30")
        if per <= 0 or st <= 0:
            return "—"
        days = (st / per).quantize(Decimal("0.1"))
        return str(days)

    @admin.display(description="Дней запаса (с поставками)", ordering="_coverage_for_days")
    def col_days_supply(self, obj):
        cov = getattr(obj, "_coverage_for_days", None)
        s30 = getattr(obj, "_sold_30", None) or Decimal("0")
        per = s30 / Decimal("30")
        if per <= 0 or cov is None or cov <= 0:
            return "—"
        days = (cov / per).quantize(Decimal("0.1"))
        return str(days)

    @admin.display(description="Запас (неснижаемый)")
    def col_supply(self, obj):
        if obj.min_stock is None:
            return "—"
        return str(obj.min_stock)

    @staticmethod
    def _fmt_qty(v):
        if v is None:
            return "—"
        return str(v.quantize(Decimal("0.001")) if isinstance(v, Decimal) else v)

    @staticmethod
    def _fmt_money(v):
        if v is None:
            return "—"
        if isinstance(v, Decimal):
            return str(v.quantize(Decimal("0.01")))
        return str(v)
