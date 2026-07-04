# Регистрация складских моделей в разделе админки «Склад»
from django.contrib import admin

from core.admin_mixins import ReturnToReferrerMixin
from core.admin import (
    MaterialBatchAdmin,
    MaterialStockAdmin,
    ProductStockAdmin,
    WarehouseAdmin,
)

from .models import (
    MaterialBatchProxy,
    MaterialStockProxy,
    ProductStockProxy,
    WarehouseProxy,
)


class WarehouseAdminShellMixin:
    """Единый шаблон списка/формы в стиле МойСклад для всех разделов «Склад»."""

    change_list_template = "admin/warehouse/changelist.html"
    change_form_template = "admin/warehouse/change_form.html"


@admin.register(WarehouseProxy)
class WarehouseAdminProxy(WarehouseAdminShellMixin, WarehouseAdmin):
    pass


@admin.register(MaterialStockProxy)
class MaterialStockAdminProxy(WarehouseAdminShellMixin, MaterialStockAdmin):
    pass


@admin.register(ProductStockProxy)
class ProductStockAdminProxy(WarehouseAdminShellMixin, ProductStockAdmin):
    pass


@admin.register(MaterialBatchProxy)
class MaterialBatchAdminProxy(WarehouseAdminShellMixin, MaterialBatchAdmin):
    pass
