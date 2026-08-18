"""Контекст-процессоры проекта."""
from django.urls import NoReverseMatch, reverse

from .models import ProductGroup, Warehouse
from .email_verification import is_email_verified
from .storefront_roles import (
    ALLOWED_PREVIEW_ROLES,
    ROLE_CLIENT,
    ROLE_EMPLOYEE,
    ROLE_EMPLOYEE_ADMIN,
    ROLE_PREVIEW_SESSION_KEY,
    can_preview_roles,
    get_effective_role,
)


def admin_product_groups(request):
    """Добавляет product_groups в контекст на страницах админки товаров."""
    if not request.path.startswith("/admin/") or "core/product" not in request.path:
        return {}
    try:
        return {"product_groups": ProductGroup.objects.all().order_by("name")}
    except Exception:
        return {"product_groups": []}


def admin_warehouse_nav(request):
    """Ссылка остатков ГП для серой строки «Склады»."""
    if not getattr(request, "path", "").startswith("/admin/"):
        return {}
    try:
        warehouses = list(Warehouse.objects.only("id", "name"))
    except Exception:
        warehouses = []
    finished_id = None
    for warehouse in warehouses:
        name = (warehouse.name or "").casefold().replace("ё", "е")
        if "готов" in name:
            finished_id = warehouse.pk
            break
    try:
        stock_url = reverse("admin:warehouse_productstockproxy_changelist")
    except NoReverseMatch:
        stock_url = "/admin/warehouse/productstockproxy/"
    finished_url = f"{stock_url}?warehouse__id__exact={finished_id}" if finished_id else stock_url
    return {
        "nav_finished_goods_stock_url": finished_url,
    }


def storefront_cart_meta(request):
    """Добавляет в контекст кол-во позиций корзины для публичного фронтенда."""
    try:
        cart = request.session.get("store_cart", {})
    except Exception:
        return {"store_cart_total_qty": 0}
    if not isinstance(cart, dict):
        return {"store_cart_total_qty": 0}

    total_qty = 0
    for value in cart.values():
        try:
            qty = int(value)
        except (TypeError, ValueError):
            qty = 0
        if qty > 0:
            total_qty += qty
    return {"store_cart_total_qty": total_qty}


def storefront_user_role(request):
    """
    Роль интерфейса по логину:
    - client: клиент (или гость)
    - employee: сотрудник
    - employee_admin: сотрудник-администратор
    """
    role = get_effective_role(request)
    email_verified = is_email_verified(getattr(request, "user", None))
    can_preview = can_preview_roles(getattr(request, "user", None))
    preview_role = request.session.get(ROLE_PREVIEW_SESSION_KEY) if can_preview else ""

    return {
        "storefront_role": role,
        "storefront_is_client": role == ROLE_CLIENT,
        "storefront_is_employee": role in {ROLE_EMPLOYEE, ROLE_EMPLOYEE_ADMIN},
        "storefront_is_employee_admin": role == ROLE_EMPLOYEE_ADMIN,
        "storefront_email_verified": email_verified,
        "storefront_can_preview_roles": can_preview,
        "storefront_preview_role": preview_role if preview_role in ALLOWED_PREVIEW_ROLES else "",
    }
