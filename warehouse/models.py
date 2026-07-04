# Прокси-модели для раздела админки «Склад»
# (реальные модели в core)
from core.models import MaterialBatch, MaterialStock, ProductStock, Warehouse


class WarehouseProxy(Warehouse):
    class Meta:
        app_label = "warehouse"
        proxy = True
        verbose_name = "Склад"
        verbose_name_plural = "Склады"


class MaterialStockProxy(MaterialStock):
    class Meta:
        app_label = "warehouse"
        proxy = True
        verbose_name = "Остаток материала на складе"
        verbose_name_plural = "Остатки материалов на складах"


class ProductStockProxy(ProductStock):
    class Meta:
        app_label = "warehouse"
        proxy = True
        verbose_name = "Остаток продукции на складе"
        verbose_name_plural = "Остатки продукции на складах"


class MaterialBatchProxy(MaterialBatch):
    class Meta:
        app_label = "warehouse"
        proxy = True
        verbose_name = "Движение по материалу"
        verbose_name_plural = "Движения по материалам"
