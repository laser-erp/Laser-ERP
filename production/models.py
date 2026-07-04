# Прокси-модели для отображения в разделе админки «Производство»
# (реальные модели в core; здесь только app_label и порядок/названия для раздела)
from core.models import (
    LaborTimeLog,
    ProductionAssignment,
    ProductionAssignmentItem,
    ProductionBatch,
    ProductionOrder,
    ProductionStage,
    TechCard,
    TechOperation,
    TechProcess,
)


class TechCardProxy(TechCard):
    class Meta:
        app_label = "production"
        proxy = True
        verbose_name = "Техкарта"
        verbose_name_plural = "Техкарты"


class ProductionOrderProxy(ProductionOrder):
    class Meta:
        app_label = "production"
        proxy = True
        verbose_name = "Заказ на производство"
        verbose_name_plural = "Заказы на производство"


class ProductionBatchProxy(ProductionBatch):
    class Meta:
        app_label = "production"
        proxy = True
        verbose_name = "Производственная партия"
        verbose_name_plural = "Производственные партии"


class TechOperationProxy(TechOperation):
    class Meta:
        app_label = "production"
        proxy = True
        verbose_name = "Техоперация"
        verbose_name_plural = "Техоперации"


class ProductionAssignmentProxy(ProductionAssignment):
    class Meta:
        app_label = "production"
        proxy = True
        verbose_name = "Производственное задание"
        verbose_name_plural = "Производственные задания"


class ProductionAssignmentItemProxy(ProductionAssignmentItem):
    class Meta:
        app_label = "production"
        proxy = True
        verbose_name = "Выполнение этапа"
        verbose_name_plural = "Выполнение этапов"


class LaborTimeLogProxy(LaborTimeLog):
    class Meta:
        app_label = "production"
        proxy = True
        verbose_name = "Оплата труда"
        verbose_name_plural = "Оплата труда"


class TechProcessProxy(TechProcess):
    class Meta:
        app_label = "production"
        proxy = True
        verbose_name = "Техпроцесс"
        verbose_name_plural = "Техпроцессы"


class ProductionStageProxy(ProductionStage):
    class Meta:
        app_label = "production"
        proxy = True
        verbose_name = "Этап производства"
        verbose_name_plural = "Этапы производства"
