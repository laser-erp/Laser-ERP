from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from core.models import Contract, Material, Organization, Product, Warehouse
from core.services.fns import fetch_contragents

from .models import GoodsReceipt, GoodsReceiptLine, SupplierPurchaseOrder, SupplierPurchaseOrderLine


def _parse_dt(s: str) -> timezone.datetime:
    s = (s or "").strip()
    if not s:
        return timezone.now()
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return timezone.now()
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _dec(s: str) -> Decimal | None:
    s = (s or "").strip().replace(",", ".")
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


@login_required
@user_passes_test(lambda u: u.is_staff)
def goods_receipt_create(request: HttpRequest) -> HttpResponse:
    materials = list(Material.objects.all().order_by("name"))
    products = list(
        Product.objects.filter(product_kind=Product.PRODUCT_KIND_GOODS).order_by("name")
    )
    orgs = list(Organization.objects.all().order_by("name"))
    contracts = list(
        Contract.objects.select_related("our_organization", "counterparty")
        .filter(status__in=[Contract.STATUS_ACTIVE, Contract.STATUS_DRAFT])
        .order_by("-contract_date", "-id")
    )
    warehouses = list(Warehouse.objects.all().order_by("name"))

    materials_payload = [{"id": m.pk, "name": m.name} for m in materials]
    products_payload = [
        {"id": p.pk, "name": p.name}
        for p in products
        if (p.name or "").strip()
    ]
    now_local = timezone.localtime(timezone.now())
    default_dt = now_local.strftime("%Y-%m-%dT%H:%M")

    po_lines_payload: list[dict] = []
    pol_qs = (
        SupplierPurchaseOrderLine.objects.filter(
            purchase_order__status__in=SupplierPurchaseOrder.INCOMING_STATUSES,
        )
        .select_related("purchase_order", "product", "material")
        .order_by("purchase_order_id", "pk")
    )
    for pol in pol_qs:
        rem = (pol.quantity - pol.quantity_received).quantize(Decimal("0.0001"))
        if rem <= 0:
            continue
        po_lines_payload.append(
            {
                "id": pol.pk,
                "supplier_id": pol.purchase_order.supplier_id,
                "material_id": pol.material_id,
                "product_id": pol.product_id,
                "label": str(pol),
                "remaining": str(rem),
            }
        )

    if request.method == "POST":
        action = (request.POST.get("form_action") or "save").strip()
        number = (request.POST.get("number") or "").strip()
        received_at = _parse_dt(request.POST.get("received_at") or "")
        org_id = request.POST.get("our_organization") or ""
        sup_id = request.POST.get("supplier") or ""
        contract_id = request.POST.get("contract_ref") or ""
        supplier_inn = (request.POST.get("supplier_inn") or "").strip()
        wh_id = request.POST.get("warehouse") or ""
        project = (request.POST.get("project") or "").strip()
        contract = (request.POST.get("contract") or "").strip()
        incoming_number = (request.POST.get("incoming_number") or "").strip()
        incoming_date = (request.POST.get("incoming_document_date") or "").strip()
        comment = (request.POST.get("comment") or "").strip()
        do_post = request.POST.get("is_posted") == "on"

        if action == "lookup_inn":
            if not supplier_inn:
                messages.error(request, "Введите ИНН для поиска контрагента.")
            else:
                try:
                    found = fetch_contragents(supplier_inn)
                    if not found:
                        messages.warning(request, "По указанному ИНН контрагент не найден.")
                    else:
                        payload = found[0]
                        inn_norm = "".join(ch for ch in str(payload.get("inn") or "") if ch.isdigit())
                        org = None
                        if inn_norm:
                            for candidate in Organization.objects.all().only("id", "inn"):
                                cand_inn = "".join(ch for ch in str(candidate.inn or "") if ch.isdigit())
                                if cand_inn == inn_norm:
                                    org = candidate
                                    break
                        if not org:
                            org = Organization.objects.create(
                                name=(payload.get("name") or "Новый контрагент").strip(),
                                inn=(payload.get("inn") or "").strip(),
                                kpp=(payload.get("kpp") or "").strip(),
                                ogrn=(payload.get("ogrn") or "").strip(),
                                legal_address=(payload.get("legal_address") or "").strip(),
                                is_individual=bool(payload.get("is_individual")),
                                is_supplier=True,
                                is_buyer=True,
                            )
                            messages.success(
                                request,
                                f"Контрагент создан: {org.name}. Выбран в поле «Контрагент».",
                            )
                        else:
                            messages.success(
                                request,
                                f"Найден существующий контрагент: {org.name}. Выбран в поле «Контрагент».",
                            )
                        sup_id = str(org.pk)
                except Exception as exc:  # noqa: BLE001
                    messages.error(request, f"Ошибка поиска по ИНН: {exc}")
            return render(
                request,
                "procurement/goods_receipt_create.html",
                {
                    "materials": materials,
                    "materials_json": materials_payload,
                    "products_json": products_payload,
                    "po_lines_json": po_lines_payload,
                    "organizations": orgs,
                    "warehouses": warehouses,
                    "contracts": contracts,
                    "default_datetime": default_dt,
                    "user_display": request.user.get_full_name() or request.user.get_username(),
                    "selected_supplier_id": int(sup_id) if sup_id.isdigit() else None,
                    "selected_contract_id": int(contract_id) if contract_id.isdigit() else None,
                    "supplier_inn": supplier_inn,
                },
            )

        line_types = request.POST.getlist("line_line_type")
        line_m = request.POST.getlist("line_material")
        line_prod = request.POST.getlist("line_product")
        line_pol = request.POST.getlist("line_po_line")
        line_q = request.POST.getlist("line_qty")
        line_p = request.POST.getlist("line_price")

        errors: list[str] = []
        if not sup_id.isdigit():
            errors.append("Укажите контрагента.")
        if not wh_id.isdigit():
            errors.append("Укажите склад.")
        if org_id and not org_id.isdigit():
            errors.append("Некорректная организация.")
        if contract_id and not contract_id.isdigit():
            errors.append("Некорректный договор.")
        if do_post and not contract_id.isdigit():
            errors.append("Для проведения приёмки выберите договор.")
        selected_contract = (
            Contract.objects.select_related("our_organization", "counterparty").filter(pk=int(contract_id)).first()
            if contract_id.isdigit()
            else None
        )
        if contract_id.isdigit() and not selected_contract:
            errors.append("Выбранный договор не найден.")
        if selected_contract and sup_id.isdigit() and selected_contract.counterparty_id != int(sup_id):
            errors.append("Выбранный договор относится к другому контрагенту.")
        if selected_contract and org_id.isdigit() and selected_contract.our_organization_id != int(org_id):
            errors.append("Выбранный договор относится к другой нашей организации.")

        n_rows = max(
            len(line_types),
            len(line_m),
            len(line_prod),
            len(line_pol),
            len(line_q),
            len(line_p),
        )
        parsed_lines: list[dict] = []
        for i in range(n_rows):
            lt = (line_types[i] if i < len(line_types) else "material").strip() or "material"
            mid = (line_m[i] if i < len(line_m) else "").strip()
            pid = (line_prod[i] if i < len(line_prod) else "").strip()
            pol_s = (line_pol[i] if i < len(line_pol) else "").strip()
            q = _dec(line_q[i] if i < len(line_q) else "")
            p = _dec(line_p[i] if i < len(line_p) else "")

            row_label = f"Строка {i + 1}"

            if q is None or q <= 0:
                if (lt == "material" and mid.isdigit()) or (lt == "product" and pid.isdigit()):
                    errors.append(f"{row_label}: укажите количество больше нуля.")
                continue

            if p is None or p < 0:
                p = Decimal("0")

            pol_id: int | None = int(pol_s) if pol_s.isdigit() else None
            material_id: int | None = None
            product_id: int | None = None

            if lt == "product":
                if not pid.isdigit():
                    errors.append(f"{row_label}: выберите товар.")
                    continue
                product_id = int(pid)
            else:
                if not mid.isdigit():
                    errors.append(f"{row_label}: выберите материал.")
                    continue
                material_id = int(mid)

            if pol_id is not None:
                try:
                    pol = SupplierPurchaseOrderLine.objects.select_related("purchase_order").get(
                        pk=pol_id
                    )
                except SupplierPurchaseOrderLine.DoesNotExist:
                    errors.append(f"{row_label}: строка заказа не найдена.")
                    continue
                if not sup_id.isdigit() or pol.purchase_order.supplier_id != int(sup_id):
                    errors.append(f"{row_label}: строка заказа от другого поставщика.")
                    continue
                if material_id is not None:
                    if pol.material_id != material_id:
                        errors.append(f"{row_label}: строка заказа не для этого материала.")
                        continue
                elif product_id is not None:
                    if pol.product_id != product_id:
                        errors.append(f"{row_label}: строка заказа не для этого товара.")
                        continue

            parsed_lines.append(
                {
                    "material_id": material_id,
                    "product_id": product_id,
                    "supplier_order_line_id": pol_id,
                    "quantity": q,
                    "unit_price": p,
                }
            )

        if do_post and not parsed_lines:
            errors.append(
                "Чтобы провести приёмку, добавьте хотя бы одну строку с материалом или товаром."
            )

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            try:
                with transaction.atomic():
                    gr = GoodsReceipt(
                        received_at=received_at,
                        supplier_id=int(sup_id),
                        warehouse_id=int(wh_id),
                        our_organization_id=int(org_id) if org_id.isdigit() else None,
                        project=project,
                        contract=(selected_contract.number if selected_contract else contract),
                        contract_ref_id=selected_contract.pk if selected_contract else None,
                        incoming_number=incoming_number,
                        comment=comment,
                        status=GoodsReceipt.STATUS_DRAFT,
                    )
                    if incoming_date:
                        try:
                            gr.incoming_document_date = date_cls.fromisoformat(incoming_date)
                        except ValueError:
                            pass
                    gr.save()
                    if number:
                        if not GoodsReceipt.objects.exclude(pk=gr.pk).filter(number=number).exists():
                            GoodsReceipt.objects.filter(pk=gr.pk).update(number=number)
                            gr.number = number

                    for pl in parsed_lines:
                        line = GoodsReceiptLine(
                            goods_receipt=gr,
                            material_id=pl["material_id"],
                            product_id=pl["product_id"],
                            supplier_order_line_id=pl["supplier_order_line_id"],
                            quantity=pl["quantity"],
                            unit_price=pl["unit_price"],
                        )
                        line.full_clean()
                        line.save()
                    gr.refresh_from_db()
                    gr.recalc_total_from_lines()
                    GoodsReceipt.objects.filter(pk=gr.pk).update(total_amount=gr.total_amount)

                    if do_post:
                        GoodsReceipt.objects.filter(pk=gr.pk).update(status=GoodsReceipt.STATUS_POSTED)
                        gr.refresh_from_db()
                        gr.conduct()

                messages.success(request, "Приёмка сохранена.")
                return redirect(reverse("admin:procurement_goodsreceipt_change", args=[gr.pk]))
            except ValidationError as ex:
                if ex.error_dict:
                    for errs in ex.error_dict.values():
                        for e in errs:
                            messages.error(request, e)
                else:
                    for msg in ex.messages:
                        messages.error(request, msg)
            except Exception as ex:  # noqa: BLE001
                messages.error(request, str(ex))

    ctx = {
        "materials": materials,
        "materials_json": materials_payload,
        "products_json": products_payload,
        "po_lines_json": po_lines_payload,
        "organizations": orgs,
        "warehouses": warehouses,
        "contracts": contracts,
        "default_datetime": default_dt,
        "user_display": request.user.get_full_name() or request.user.get_username(),
        "selected_supplier_id": None,
        "selected_contract_id": None,
        "supplier_inn": "",
    }
    return render(request, "procurement/goods_receipt_create.html", ctx)
