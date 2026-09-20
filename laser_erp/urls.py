"""
URL configuration for laser_erp project.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse
from django.urls import reverse_lazy

from core.views_password_reset import (
    AccountPasswordResetDoneView,
    AccountPasswordResetView,
    LaserPasswordResetDoneView,
    LaserPasswordResetView,
)

# Блок на главной /admin/: материалы + движения + группы + «Товары и услуги» (одна точка входа).
_NOMENCLATURE_MODEL_ORDER = (
    "materialgroup",
    "material",
    "materialbatch",
    "productgroup",
    "servicegroup",
    "product",
)
_NOMENCLATURE_MODEL_SET = frozenset(_NOMENCLATURE_MODEL_ORDER)
_ACCOUNTING_MODEL_ORDER = (
    "expenseledgerentry",
)
_ACCOUNTING_MODEL_SET = frozenset(_ACCOUNTING_MODEL_ORDER)

# Модели склада и производства скрыты из раздела Core (показываются в своих разделах)
_WAREHOUSE_MODEL_NAMES = {
    "warehouse",
    "materialstock",
    "productstock",
    "materialbatch",
}
_PRODUCTION_MODEL_NAMES = {
    "techcard",
    "productionorder",
    "productionbatch",
    "techoperation",
    "productionstage",
    "techprocess",
    "productionassignment",
    "productionassignmentitem",
    "labortimelog",
}


def _get_app_list_with_production_grouped(request, app_label=None):
    """
    Подмена admin.site.get_app_list: вызывается как обычная функция на экземпляре
    (без self) — аргументы (request) или (request, app_label).
    """
    original = AdminSite.get_app_list(admin.site, request, app_label)
    _hidden_from_core = _WAREHOUSE_MODEL_NAMES | _PRODUCTION_MODEL_NAMES

    def _strip_core_models(models):
        return [
            m
            for m in models
            if (m.get("object_name") or "").lower() not in _hidden_from_core
        ]

    # Страница /admin/core/ — только фильтр «лишнего» из core, без виртуального блока.
    if app_label is not None:
        for app in original:
            if app.get("app_label") == "core" and "models" in app:
                app["models"] = _strip_core_models(app["models"])
        return original

    nomenclature_models = []
    accounting_models = []
    out = []
    for app in original:
        if app.get("app_label") in ("warehouse", "procurement"):
            continue
        if app.get("app_label") != "core":
            out.append(app)
            continue

        raw_models = app.get("models") or []
        by_lower = {(m.get("object_name") or "").lower(): m for m in raw_models}
        for key in _NOMENCLATURE_MODEL_ORDER:
            if key in by_lower:
                nomenclature_models.append(by_lower[key])
        for key in _ACCOUNTING_MODEL_ORDER:
            if key in by_lower:
                accounting_models.append(by_lower[key])

        stripped = _strip_core_models(raw_models)
        taken = _NOMENCLATURE_MODEL_SET | _ACCOUNTING_MODEL_SET
        app_core = {
            **app,
            "models": [
                m
                for m in stripped
                if (m.get("object_name") or "").lower() not in taken
            ],
        }
        out.append(app_core)

    if nomenclature_models:
        try:
            nom_url = reverse(
                "admin:core_product_changelist",
                current_app=admin.site.name,
            )
        except Exception:
            nom_url = reverse(
                "admin:core_material_changelist",
                current_app=admin.site.name,
            )
        out.insert(
            0,
            {
                "name": "Номенклатура",
                "app_label": "core_nomenclature",
                "app_url": nom_url,
                "has_module_perms": True,
                "models": nomenclature_models,
            },
        )
    if accounting_models:
        try:
            accounting_url = reverse(
                "admin:core_expenseledgerentry_changelist",
                current_app=admin.site.name,
            )
        except Exception:
            accounting_url = reverse("admin:index", current_app=admin.site.name)
        out.insert(
            1 if nomenclature_models else 0,
            {
                "name": "Бухгалтерия",
                "app_label": "core_accounting",
                "app_url": accounting_url,
                "has_module_perms": True,
                "models": accounting_models,
            },
        )

    return out


admin.site.get_app_list = _get_app_list_with_production_grouped

urlpatterns = [
    path(
        "admin/password_reset/",
        LaserPasswordResetView.as_view(),
        name="admin_password_reset",
    ),
    path(
        "admin/password_reset/done/",
        LaserPasswordResetDoneView.as_view(),
        name="admin_password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="registration/password_reset_confirm.html",
            success_url=reverse_lazy("password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="registration/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("production/", include(("production.urls", "production"))),
    path("", include("procurement.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
