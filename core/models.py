from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Prefetch, Q, Sum
from django.utils import timezone
from decimal import ROUND_HALF_UP, ROUND_UP, Decimal
import re
from uuid import uuid4


def operation_type_name_to_result_adjective(operation_name: str) -> str:
    """
    Прилагательное для наименования товара по названию типа операции.
    Точные варианты и окончание «…ние» → «…ный» (шлифование → шлифованный).
    """
    n = (operation_name or "").strip()
    if not n:
        return ""
    low = n.lower()
    exact = {
        "шлифование": "шлифованный",
        "покраска": "окрашенный",
        "лакировка": "лакированный",
        "сверление": "сверлёный",
        "резка": "резаный",
        "раскрой": "раскроенный",
        "фрезеровка": "фрезерованный",
        "тиснение": "тиснёный",
        "сушка": "высушенный",
        "склейка": "склеенный",
    }
    if low in exact:
        return exact[low]
    if low.endswith("ние") and len(low) > 4:
        return low[:-2] + "ный"
    return n


class MaterialGroup(models.Model):
    """Группа материалов (например: Фанера, Листы для резки)."""
    name = models.CharField("Наименование", max_length=255)
    description = models.TextField("Описание", blank=True)

    class Meta:
        verbose_name = "Группа материалов"
        verbose_name_plural = "Группы материалов"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Material(models.Model):
    name = models.CharField("Наименование", max_length=255)
    group = models.ForeignKey(
        MaterialGroup,
        verbose_name="Группа",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="materials",
    )
    material_type = models.CharField("Тип материала", max_length=100, blank=True)
    thickness_mm = models.DecimalField(
        "Толщина (мм)",
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Толщина в миллиметрах",
    )
    sheet_length_mm = models.DecimalField(
        "Длина листа, мм",
        max_digits=12,
        decimal_places=0,
        null=True,
        blank=True,
        help_text="Длина листа/заготовки в мм. Вместе с шириной используется для расчёта площади листа.",
    )
    sheet_width_mm = models.DecimalField(
        "Ширина листа, мм",
        max_digits=12,
        decimal_places=0,
        null=True,
        blank=True,
        help_text="Ширина листа/заготовки в мм.",
    )
    area_m2 = models.DecimalField(
        "Пл. листа, м²",
        max_digits=14,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Считается из длины × ширины (мм). Для ед. «лист» — площадь одного листа.",
    )
    sheet_area_mm2 = models.DecimalField(
        "Пл. листа, мм²",
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        editable=False,
    )
    sheet_area_cm2 = models.DecimalField(
        "Пл. листа, см²",
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        editable=False,
    )
    unit = models.CharField(
        "Ед. измерения",
        max_length=50,
        help_text="Единица измерения (лист, м2, м, кг и т.п.)",
    )
    current_stock = models.DecimalField("Текущий остаток", max_digits=12, decimal_places=3, default=0)
    photo = models.ImageField(
        "Фото",
        upload_to="materials/",
        blank=True,
        null=True,
    )

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name = "Материал"
        verbose_name_plural = "Материалы"

    def apply_sheet_geometry(self) -> None:
        """Площадь листа из Д×Ш (мм), как у товара."""
        self.sheet_area_mm2 = None
        self.sheet_area_cm2 = None
        self.area_m2 = None
        L = self.sheet_length_mm
        W = self.sheet_width_mm
        if L is None or W is None:
            return
        try:
            ln = Decimal(str(L))
            wd = Decimal(str(W))
        except Exception:
            return
        if ln <= 0 or wd <= 0:
            return
        mm2 = (ln * wd).quantize(Decimal("0.01"))
        self.sheet_area_mm2 = mm2
        self.sheet_area_cm2 = (mm2 / Decimal("100")).quantize(Decimal("0.01"))
        self.area_m2 = (mm2 / Decimal("1000000")).quantize(Decimal("0.000001"))

    def save(self, *args, **kwargs):
        for attr in ("sheet_length_mm", "sheet_width_mm"):
            v = getattr(self, attr, None)
            if v is not None:
                setattr(self, attr, Decimal(str(v)).quantize(Decimal("1")))
        self.apply_sheet_geometry()
        super().save(*args, **kwargs)

    @property
    def average_price(self) -> Decimal | None:
        """Средняя цена за единицу по приёмкам (поступлениям IN)."""
        agg = (
            self.batches.filter(movement_type=MaterialBatch.INCOMING)
            .aggregate(
                total_qty=Sum("quantity"),
                total_cost=Sum(F("quantity") * F("unit_price")),
            )
        )
        total_qty = agg["total_qty"]
        total_cost = agg["total_cost"]
        if not total_qty or not total_cost:
            return None
        return (total_cost / total_qty).quantize(Decimal("0.0001"))


class MaterialBatch(models.Model):
    INCOMING = "IN"
    OUTGOING = "OUT"
    ADJUSTMENT = "ADJ"

    MOVEMENT_TYPES = [
        (INCOMING, "Поступление"),
        (OUTGOING, "Списание"),
        (ADJUSTMENT, "Корректировка"),
    ]

    material = models.ForeignKey(
        Material,
        verbose_name="Материал",
        on_delete=models.CASCADE,
        related_name="batches",
    )
    movement_type = models.CharField(
        "Тип движения",
        max_length=3,
        choices=MOVEMENT_TYPES,
        default=INCOMING,
    )
    quantity = models.DecimalField("Количество", max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(
        "Цена за единицу",
        max_digits=12,
        decimal_places=4,
        help_text="Цена за единицу в момент движения",
    )
    date = models.DateTimeField("Дата", auto_now_add=True)
    comment = models.CharField("Комментарий", max_length=255, blank=True)

    class Meta:
        verbose_name = "Движение по материалу"
        verbose_name_plural = "Движения по материалам"
        ordering = ["-date"]

    def __str__(self) -> str:
        return f"{self.material} {self.get_movement_type_display()} {self.quantity} {self.material.unit}"


class ProductGroup(models.Model):
    """Группа товаров. Для товаров с материалом и операцией имя часто задаётся как «материал + тип операции»."""
    name = models.CharField("Название", max_length=255)
    description = models.TextField("Описание", blank=True)

    class Meta:
        verbose_name = "Группа товаров"
        verbose_name_plural = "Группы товаров"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ServiceGroup(models.Model):
    """Группа услуг: объединяет выбранные услуги из справочника."""
    name = models.CharField("Название", max_length=255)
    description = models.TextField("Описание", blank=True)
    services = models.ManyToManyField(
        "Product",
        verbose_name="Услуги",
        related_name="service_groups",
        blank=True,
        limit_choices_to={"product_kind": "service"},
        help_text="Выберите услуги из справочника",
    )

    class Meta:
        verbose_name = "Группа услуг"
        verbose_name_plural = "Группы услуг"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Product(models.Model):
    """
    Карточка товара (изделия). Наименование, учёт, цены, изображение,
    группа, артикул/коды, единица измерения, вес/объём, закупочная и минимальная цена,
    неснижаемый остаток, поставщик, страна, аналоги.
    """
    name = models.CharField(
        "Наименование",
        max_length=255,
        blank=True,
        help_text="Для товара: при первом материале, норме времени с типом операции и длине/ширине в мм "
        "пересобирается из материала, прилагательного операции и размеров; группа — «материал + операция». "
        "Иначе введите наименование вручную и выберите группу.",
    )
    description = models.TextField("Описание", blank=True)
    # Группа и категория (категория — текст для совместимости)
    product_group = models.ForeignKey(
        ProductGroup,
        verbose_name="Группа товаров",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    material_group = models.ForeignKey(
        MaterialGroup,
        verbose_name="Группа материалов",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products_as_material_nomenclature",
        help_text="Только для вида «Материал»: та же классификация, что у складского справочника материалов.",
    )
    category = models.CharField("Категория", max_length=100, blank=True)
    PRODUCT_KIND_GOODS = "goods"
    PRODUCT_KIND_SERVICE = "service"
    PRODUCT_KIND_MATERIAL = "material"
    PRODUCT_KIND_CHOICES = [
        (PRODUCT_KIND_GOODS, "Товар"),
        (PRODUCT_KIND_SERVICE, "Услуга"),
        (PRODUCT_KIND_MATERIAL, "Материал"),
    ]
    product_kind = models.CharField(
        "Вид",
        max_length=20,
        choices=PRODUCT_KIND_CHOICES,
        default=PRODUCT_KIND_GOODS,
        help_text="Товар, услуга или материал — для разделения в навигации и отчётах",
    )
    # Идентификация и поиск
    article = models.CharField(
        "Артикул",
        max_length=100,
        blank=True,
        help_text="Если оставить пустым, при сохранении присвоится автоматически (ART-000123).",
    )
    code = models.CharField("Код", max_length=100, blank=True)
    external_code = models.CharField("Внешний код", max_length=100, blank=True)
    # Единица измерения, вес, объём
    unit = models.CharField(
        "Ед. изм.",
        max_length=50,
        default="шт",
        help_text="В карточке — список частых значений; можно ввести любую ед. изм. (шт, м, м², кг и т.п.).",
    )
    weight_kg = models.DecimalField(
        "Вес",
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Килограммы",
    )
    volume = models.DecimalField(
        "Объём м³",
        max_digits=12,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Значение в м³. Для ед. шт: из Д×Ш×Т (мм). Для м²: из пл.×толщина. Для п.м: из длины (м)×Ш×Т (мм).",
    )
    # Габариты, пл. (мм², см², м²) и объём — по единице измерения
    sheet_length_mm = models.DecimalField(
        "Длина в мм",
        max_digits=12,
        decimal_places=0,
        null=True,
        blank=True,
        help_text="Целые мм. Ед. шт — длина листа/заготовки; ед. п.м — не для длины (см. «Длина в м»)",
    )
    sheet_width_mm = models.DecimalField(
        "Ширина в мм",
        max_digits=12,
        decimal_places=0,
        null=True,
        blank=True,
        help_text="Целые мм. Ед. шт — ширина листа; ед. п.м — размер сечения",
    )
    sheet_thickness_mm = models.DecimalField(
        "Толщина в мм",
        max_digits=12,
        decimal_places=0,
        null=True,
        blank=True,
        help_text="Целые мм. Ед. шт — толщина листа; ед. м² — слой; ед. п.м — сечение с шириной",
    )
    area_m2_manual = models.DecimalField(
        "Пл. в м²",
        max_digits=14,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Ед. м² / кв. м — ввод вручную. Ед. шт — считается из длины × ширины (мм), только просмотр.",
    )
    length_m_manual = models.DecimalField(
        "Длина в м",
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Ед. шт — из «Длина в мм» ÷ 1000 (авто). Ед. п.м / м — вручную; объём = длина × ширина × толщина сечения (мм→м³).",
    )
    sheet_area_mm2 = models.DecimalField(
        "Пл. в мм²",
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        editable=False,
        help_text="Авто: ед. шт — Д×Ш; ед. м² — из пл. (м²)",
    )
    sheet_area_cm2 = models.DecimalField(
        "Пл. в см²",
        max_digits=16,
        decimal_places=2,
        null=True,
        blank=True,
        editable=False,
        help_text="Авто из мм² или из пл. (м²)",
    )
    # Цены
    purchase_price = models.DecimalField(
        "Закупочная цена",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Подставляется в документы закупки; для дерева себестоимости",
    )
    planned_price = models.DecimalField(
        "Плановая цена продажи",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Плановая цена продажи за единицу",
    )
    min_price = models.DecimalField(
        "Минимальная цена",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Ограничение: не продавать ниже этой цены",
    )
    planned_markup_percent = models.DecimalField(
        "Наценка к плановой цене, %",
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Вкладка «Стоимость»: плановая по формуле закупочная × (1 + %/100). Поля на вкладке «Цены» подставляются только по кнопкам.",
    )
    # Остатки и учёт
    min_stock = models.DecimalField(
        "Неснижаемый остаток",
        max_digits=12,
        decimal_places=0,
        null=True,
        blank=True,
        default=0,
        help_text="Целое число единиц учёта (дробная часть при сохранении округляется)",
    )
    track_lots = models.BooleanField(
        "Учёт по партиям",
        default=False,
        help_text="Учёт товара по партиям и срокам годности",
    )
    # Поставщик и страна (организация из справочника «Контрагенты»)
    supplier = models.ForeignKey(
        "Organization",
        verbose_name="Поставщик",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supplied_products",
        help_text="Организация из справочника контрагентов — основной поставщик по закупкам для этой номенклатуры.",
    )
    country = models.CharField("Страна происхождения", max_length=100, blank=True)
    vat_rate_percent = models.DecimalField(
        "НДС",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Ставка НДС в процентах (например 20 или 10).",
    )
    # Изображение (обложка)
    photo = models.ImageField(
        "Изображение",
        upload_to="products/",
        blank=True,
        null=True,
    )

    def __str__(self) -> str:
        n = (self.name or "").strip()
        if n:
            return n
        if self.pk:
            return f"Товар #{self.pk}"
        return "Новый товар"

    class Meta:
        verbose_name = "Товар (изделие)"
        verbose_name_plural = "Товары и услуги"
        ordering = ["name"]

    def get_search_display(self):
        """Строка для поиска: название, артикул, код."""
        parts = [(self.name or "").strip() or self.__str__()]
        if self.article:
            parts.append(f"арт. {self.article}")
        if self.code:
            parts.append(f"код {self.code}")
        return " | ".join(parts)

    def computed_purchase_cost_from_materials(self):
        """
        Закупочная себестоимость по составу: Σ (средняя цена материала × расход на 1 изделие), ₽.
        Средняя цена материала — из приёмки (поступления MaterialBatch IN с ценой за единицу);
        строки без неё в сумму не входят.
        """
        total = Decimal("0")
        used = 0
        for pm in self.materials.select_related("material").all():
            qty = pm.quantity_per_unit
            if qty is None:
                continue
            ap = pm.material.average_price
            if ap is None:
                continue
            total += ap * qty
            used += 1
        if used == 0:
            return None
        return total.quantize(Decimal("0.01"))

    def normalized_uom_kind(self) -> str:
        """piece | sqm | meter | other — по полю unit (для расчёта пл.)."""
        raw = (self.unit or "").strip()
        u = raw.lower().replace(" ", "").replace("\xa0", "")
        if not u:
            return "other"
        piece = {"шт", "штук", "штука", "pcs", "pc", "шт.", "штуки"}
        if u in piece:
            return "piece"
        if u in ("м²", "m²", "м2", "m2", "кв.м", "квм", "sq.m", "sqm"):
            return "sqm"
        if "кв" in u and ("м" in u or "m" in u):
            return "sqm"
        if "м²" in raw or "m²" in raw.lower():
            return "sqm"
        if u in ("м", "m", "п.м", "пм", "пог.м", "погм", "л.м", "lm"):
            return "meter"
        return "other"

    def apply_derived_geometry(self) -> None:
        """
        Пл. в мм², см², м² и объём в м³ по единице измерения.
        шт: пл. Д×Ш; объём Д×Ш×Т (мм³→м³).
        м²: пл. из поля м²; объём пл.×(Т/1000).
        п.м: объём длина_м×1000×Ш×Т в мм³→м³; пл. не считается.
        шт: длина в м = длина (мм) / 1000.
        """
        kind = self.normalized_uom_kind()
        self.sheet_area_mm2 = None
        self.sheet_area_cm2 = None
        vol_m3 = None

        if kind == "piece":
            L = self.sheet_length_mm
            W = self.sheet_width_mm
            T = self.sheet_thickness_mm
            if L is not None and L > 0:
                self.length_m_manual = (L / Decimal("1000")).quantize(Decimal("0.0001"))
            else:
                self.length_m_manual = None
            if L is not None and W is not None and L > 0 and W > 0:
                mm2 = (L * W).quantize(Decimal("0.001"))
                self.sheet_area_mm2 = mm2.quantize(Decimal("0.01"))
                self.sheet_area_cm2 = (mm2 / Decimal("100")).quantize(Decimal("0.01"))
                self.area_m2_manual = (mm2 / Decimal("1000000")).quantize(Decimal("0.01"))
            else:
                self.area_m2_manual = None
            if (
                L is not None
                and W is not None
                and T is not None
                and L > 0
                and W > 0
                and T > 0
            ):
                mm3 = (L * W * T).quantize(Decimal("0.001"))
                vol_m3 = (mm3 / Decimal("1000000000")).quantize(Decimal("0.000001"))
        elif kind == "sqm":
            a = self.area_m2_manual
            T = self.sheet_thickness_mm
            if a is not None and a > 0:
                m2 = a.quantize(Decimal("0.01"))
                self.sheet_area_cm2 = (m2 * Decimal("10000")).quantize(Decimal("0.01"))
                mm2 = m2 * Decimal("1000000")
                self.sheet_area_mm2 = mm2.quantize(Decimal("0.01"))
            if a is not None and T is not None and a > 0 and T > 0:
                m2_vol = a.quantize(Decimal("0.01"))
                vol_m3 = (m2_vol * (T / Decimal("1000"))).quantize(Decimal("0.000001"))
        elif kind == "meter":
            Lm = self.length_m_manual
            W = self.sheet_width_mm
            T = self.sheet_thickness_mm
            if Lm is not None and W is not None and T is not None and Lm > 0 and W > 0 and T > 0:
                L_mm = Lm * Decimal("1000")
                mm3 = (L_mm * W * T).quantize(Decimal("0.001"))
                vol_m3 = (mm3 / Decimal("1000000000")).quantize(Decimal("0.000001"))

        if vol_m3 is not None:
            self.volume = vol_m3

    def _mm_segment_for_goods_name(self, value: Decimal | None) -> str | None:
        if value is None or value <= 0:
            return None
        return str(int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))

    def _primary_material_name(self) -> str | None:
        """Первый материал из вкладки «Материалы» (по pk)."""
        if not self.pk:
            return None
        pm = self.materials.select_related("material").order_by("pk").first()
        if not pm or not pm.material_id:
            return None
        m = (pm.material.name or "").strip()
        return m or None

    def _primary_operation_type(self):
        """Первая норма времени / тип операции (по pk)."""
        if not self.pk:
            return None
        pl = self.labor_norms.select_related("operation_type").order_by("pk").first()
        if not pl or not pl.operation_type_id:
            return None
        return pl.operation_type

    def _operation_result_adjective(self, operation_type) -> str:
        if operation_type is None:
            return ""
        custom = (getattr(operation_type, "result_adjective", None) or "").strip()
        if custom:
            return custom
        return operation_type_name_to_result_adjective(operation_type.name or "")

    def _composed_goods_group_label(self) -> str | None:
        """Название группы: материал + тип операции (как в справочнике)."""
        mat = self._primary_material_name()
        ot = self._primary_operation_type()
        if not mat or not ot:
            return None
        op = (ot.name or "").strip()
        if not op:
            return None
        s = f"{mat} {op}".strip()
        return s[:255] if len(s) > 255 else s

    def _composed_goods_full_name(self) -> str | None:
        """Наименование: материал + прилагательное операции + габариты в мм."""
        if self.product_kind != self.PRODUCT_KIND_GOODS:
            return None
        mat = self._primary_material_name()
        ot = self._primary_operation_type()
        if not mat or not ot:
            return None
        adj = self._operation_result_adjective(ot)
        if not adj:
            adj = (ot.name or "").strip()
        ls = self._mm_segment_for_goods_name(self.sheet_length_mm)
        ws = self._mm_segment_for_goods_name(self.sheet_width_mm)
        if not ls or not ws:
            return None
        ts = self._mm_segment_for_goods_name(self.sheet_thickness_mm)
        parts = [mat, adj, f"{ls}×{ws}"]
        if ts:
            parts.append(ts)
        parts.append("мм")
        s = " ".join(parts)
        return s[:255] if len(s) > 255 else s

    def composed_goods_name(self) -> str | None:
        """Полное авто-наименование товара (материал, операция, размеры)."""
        return self._composed_goods_full_name()

    def apply_composed_goods_identity(self) -> bool:
        """
        Подставляет группу (get_or_create по «материал + операция») и наименование по правилам.
        Возвращает True, если изменились name или product_group_id.
        """
        if self.product_kind != self.PRODUCT_KIND_GOODS:
            return False
        old_name = self.name
        old_gid = self.product_group_id
        label = self._composed_goods_group_label()
        if label:
            grp, _ = ProductGroup.objects.get_or_create(
                name=label,
                defaults={"description": ""},
            )
            self.product_group = grp
        full = self._composed_goods_full_name()
        if full:
            self.name = full
        changed = self.product_group_id != old_gid or self.name != old_name
        return changed

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError

        if self.composed_goods_name():
            return
        if not (self.name or "").strip():
            if self.product_kind == self.PRODUCT_KIND_GOODS:
                if self.pk:
                    raise ValidationError(
                        {
                            "name": "Для товара задайте первый материал, норму времени с типом операции "
                            "и положительные длину и ширину в мм (наименование и группа подставятся при сохранении) "
                            "или введите наименование вручную.",
                        }
                    )
                return
            raise ValidationError({"name": "Укажите наименование."})

    def save(self, *args, **kwargs):
        if self.min_stock is not None:
            self.min_stock = self.min_stock.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        q0 = Decimal("1")
        for attr in ("sheet_length_mm", "sheet_width_mm", "sheet_thickness_mm"):
            v = getattr(self, attr)
            if v is not None:
                setattr(self, attr, v.quantize(q0, rounding=ROUND_HALF_UP))
        self.apply_derived_geometry()
        if self.product_kind == self.PRODUCT_KIND_GOODS:
            self.apply_composed_goods_identity()
        need_auto_article = not (self.article or "").strip()
        super().save(*args, **kwargs)
        if need_auto_article:
            auto = f"ART-{self.pk:06d}"
            type(self).objects.filter(pk=self.pk).update(article=auto)
            self.article = auto

    @property
    def planned_material_cost(self) -> Decimal:
        total = Decimal("0")
        for pm in self.materials.select_related("material"):
            avg_price = pm.material.average_price
            if avg_price is None:
                continue
            total += pm.quantity_per_unit * avg_price
        return total.quantize(Decimal("0.01")) if total else Decimal("0.00")

    def _primary_tech_card_for_cost(self):
        """Техкарта для плановой себестоимости (последняя сохранённая с этим изделием)."""
        if not self.pk:
            return None
        return (
            self.tech_cards.prefetch_related("labor_lines__production_stage", "items__material")
            .order_by("-pk")
            .first()
        )

    @property
    def planned_labor_cost(self) -> Decimal:
        tc = self._primary_tech_card_for_cost()
        if tc is not None:
            return tc.planned_labor_cost_per_unit()
        total = Decimal("0")
        for ln in self.labor_norms.select_related("operation_type"):
            minutes = ln.minutes_per_unit
            rate = ln.operation_type.hourly_rate
            total += (minutes / Decimal("60")) * rate
        return total.quantize(Decimal("0.01")) if total else Decimal("0.00")

    @property
    def planned_overhead_cost(self) -> Decimal:
        tc = self._primary_tech_card_for_cost()
        if tc is not None:
            return tc.planned_overhead_per_unit()
        return Decimal("0.00")

    @property
    def planned_cut_cost(self) -> Decimal:
        """Рез по метрам: сумма по всем техкартам изделия."""
        tc = self._primary_tech_card_for_cost()
        if tc is not None:
            return tc.planned_cut_cost_per_unit()
        total = Decimal("0")
        for tc in self.tech_cards.all():
            total += tc.planned_cut_cost_per_unit()
        return total.quantize(Decimal("0.01"))

    @property
    def planned_total_cost(self) -> Decimal:
        return (
            self.planned_material_cost
            + self.planned_labor_cost
            + self.planned_overhead_cost
            + self.planned_cut_cost
        ).quantize(Decimal("0.01"))

    def get_quick_sale_price(
        self,
        *,
        default_markup_percent: Decimal = Decimal("40"),
        round_step: Decimal = Decimal("10"),
    ) -> Decimal:
        """
        Быстрый расчёт цены продажи для единицы:
        полная плановая себестоимость + наценка (%) + округление вверх.
        """
        base_cost = self.planned_total_cost or Decimal("0")
        markup_percent = (
            self.planned_markup_percent
            if self.planned_markup_percent is not None
            else default_markup_percent
        )
        price = base_cost * (Decimal("1") + (markup_percent / Decimal("100")))
        if round_step and round_step > 0:
            steps = (price / round_step).to_integral_value(rounding=ROUND_UP)
            price = steps * round_step
        return price.quantize(Decimal("0.01"))


class ProductBarcode(models.Model):
    """
    Штрихкод товара. Один товар может иметь несколько штрихкодов
    (например, основной EAN13 и коды упаковок). Значение штрихкода уникально в системе.
    """
    EAN13 = "EAN13"
    EAN8 = "EAN8"
    CODE128 = "CODE128"
    OTHER = "OTHER"
    TYPE_CHOICES = [
        (EAN13, "EAN-13"),
        (EAN8, "EAN-8"),
        (CODE128, "Code 128"),
        (OTHER, "Другой"),
    ]

    product = models.ForeignKey(
        Product,
        verbose_name="Товар",
        on_delete=models.CASCADE,
        related_name="barcodes",
    )
    barcode_type = models.CharField(
        "Тип штрихкода",
        max_length=20,
        choices=TYPE_CHOICES,
        default=EAN13,
    )
    value = models.CharField(
        "Штрихкод",
        max_length=64,
        unique=True,
        help_text="Введите вручную или отсканируйте. Один и тот же штрихкод не может быть у разных товаров.",
    )
    comment = models.CharField(
        "Комментарий",
        max_length=255,
        blank=True,
        help_text="Например: основной, упаковка 6 шт, весовой.",
    )

    class Meta:
        verbose_name = "Штрихкод товара"
        verbose_name_plural = "Штрихкоды товаров"
        ordering = ["product", "barcode_type", "value"]

    def __str__(self) -> str:
        return f"{self.value} ({self.get_barcode_type_display()})"


class ProductGalleryImage(models.Model):
    """Дополнительные изображения товара (не более 15). Обложка в списке — первое по порядку."""

    product = models.ForeignKey(
        Product,
        verbose_name="Товар",
        on_delete=models.CASCADE,
        related_name="gallery_images",
    )
    image = models.ImageField("Файл", upload_to="products/gallery/")
    sort_order = models.PositiveSmallIntegerField("Порядок", default=0)

    class Meta:
        verbose_name = "Изображение товара"
        verbose_name_plural = "Изображения товара"
        ordering = ["product", "sort_order", "pk"]

    def __str__(self) -> str:
        return f"Фото #{self.pk} ({self.product_id})"


class ProductAnalog(models.Model):
    """Аналог товара — для подстановки при отсутствии основного (не более 10 на товар)."""
    product = models.ForeignKey(
        Product,
        verbose_name="Товар",
        on_delete=models.CASCADE,
        related_name="analog_links",
    )
    analog_product = models.ForeignKey(
        Product,
        verbose_name="Аналог",
        on_delete=models.CASCADE,
        related_name="as_analog_of",
    )
    order = models.PositiveSmallIntegerField("Порядок", default=1)

    class Meta:
        verbose_name = "Аналог товара"
        verbose_name_plural = "Аналоги товаров"
        ordering = ["product", "order"]
        unique_together = ("product", "analog_product")

    def __str__(self) -> str:
        return f"{self.product} — аналог: {self.analog_product}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.product_id and self.analog_product_id and self.product_id == self.analog_product_id:
            raise ValidationError("Товар не может быть аналогом самого себя.")
        if self.product_id and self.analog_product_id:
            count = ProductAnalog.objects.filter(product=self.product).exclude(pk=self.pk).count()
            if count >= 10:
                raise ValidationError("Нельзя добавить более 10 аналогов одному товару.")


class ProductModification(models.Model):
    """Модификация изделия: вариант SKU с собственной ценой/коэффициентом."""
    GRADE_12 = "1/2"
    GRADE_22 = "2/2"
    GRADE_24 = "2/4"
    GRADE_44 = "4/4"
    GRADE_CHOICES = [
        (GRADE_12, "1/2"),
        (GRADE_22, "2/2"),
        (GRADE_24, "2/4"),
        (GRADE_44, "4/4"),
    ]
    SANDING_ONE_SIDE = "Ш1"
    SANDING_TWO_SIDE = "Ш2"
    SANDING_CHOICES = [
        (SANDING_ONE_SIDE, "Ш1"),
        (SANDING_TWO_SIDE, "Ш2"),
    ]

    product = models.ForeignKey(
        Product,
        verbose_name="Базовое изделие",
        on_delete=models.CASCADE,
        related_name="modifications",
    )
    name = models.CharField(
        "Название модификации",
        max_length=255,
        blank=True,
        help_text="Например: «С гравировкой», «Большая 300x180 мм».",
    )
    thickness_mm = models.PositiveSmallIntegerField("Толщина, мм", null=True, blank=True)
    grade = models.CharField(
        "Сорт",
        max_length=8,
        choices=GRADE_CHOICES,
        blank=True,
    )
    sanding_sides = models.CharField(
        "Шлифование",
        max_length=8,
        choices=SANDING_CHOICES,
        blank=True,
    )
    abrasive_grit = models.CharField("Абразив", max_length=16, blank=True)
    article = models.CharField("Артикул модификации", max_length=64, blank=True)
    code = models.CharField("Код модификации", max_length=64, blank=True)
    quantity_factor = models.DecimalField(
        "Коэффициент расхода",
        max_digits=8,
        decimal_places=3,
        default=Decimal("1"),
        help_text="1.000 — как у базового изделия; 1.200 — расход/себестоимость выше на 20%.",
    )
    planned_price = models.DecimalField(
        "Цена продажи (если фикс.)",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Если заполнено — используется как цена продажи этой модификации.",
    )
    planned_markup_percent = models.DecimalField(
        "Наценка, %",
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Если «Цена продажи» пустая: себестоимость × (1 + %/100), затем округление.",
    )
    sort_order = models.PositiveSmallIntegerField("Порядок", default=1)
    is_active = models.BooleanField("Активна", default=True)
    comment = models.CharField("Комментарий", max_length=255, blank=True)

    class Meta:
        verbose_name = "Модификация товара"
        verbose_name_plural = "Модификации товаров"
        ordering = ["product", "sort_order", "name", "pk"]
        unique_together = ("product", "name")

    def __str__(self) -> str:
        return self.name or "модификация"

    def _build_name_from_params(self) -> str:
        parts = []
        if self.thickness_mm:
            parts.append(f"{self.thickness_mm} мм")
        if self.grade:
            parts.append(f"сорт {self.grade}")
        if self.sanding_sides:
            parts.append(self.sanding_sides)
        abrasive = (self.abrasive_grit or "").strip().upper()
        if abrasive:
            parts.append(abrasive)
        return " | ".join(parts)

    @staticmethod
    def parse_name_components(name: str) -> dict:
        text = (name or "").strip()
        if not text:
            return {}
        parts = [p.strip() for p in text.split("|")]
        out = {}
        for part in parts:
            if not part:
                continue
            low = part.lower()
            m = re.search(r"(\d+)\s*мм", low)
            if m:
                try:
                    out["thickness_mm"] = int(m.group(1))
                except (TypeError, ValueError):
                    pass
                continue
            if low.startswith("сорт"):
                grade = part.replace("сорт", "").strip()
                if grade in dict(ProductModification.GRADE_CHOICES):
                    out["grade"] = grade
                continue
            up = part.upper()
            if up in {"Ш1", "Ш2"}:
                out["sanding_sides"] = up
                continue
            if re.fullmatch(r"P\d{2,3}", up):
                out["abrasive_grit"] = up
        return out

    def clean(self):
        super().clean()
        if not self.name and not any(
            [self.thickness_mm, self.grade, self.sanding_sides, (self.abrasive_grit or "").strip()]
        ):
            raise ValidationError("Заполните параметры модификации или название.")

    def save(self, *args, **kwargs):
        if self.abrasive_grit:
            self.abrasive_grit = self.abrasive_grit.strip().upper()
        generated = self._build_name_from_params()
        if generated:
            self.name = generated
        elif self.name:
            self.name = self.name.strip()
        super().save(*args, **kwargs)

    @property
    def planned_cost(self) -> Decimal:
        base = self.product.planned_total_cost or Decimal("0")
        factor = self.quantity_factor or Decimal("1")
        return (base * factor).quantize(Decimal("0.01"))

    @property
    def sale_price(self) -> Decimal:
        if self.planned_price is not None:
            return self.planned_price.quantize(Decimal("0.01"))
        base_cost = self.planned_cost
        markup_percent = (
            self.planned_markup_percent
            if self.planned_markup_percent is not None
            else (
                self.product.planned_markup_percent
                if self.product.planned_markup_percent is not None
                else Decimal("40")
            )
        )
        price = base_cost * (Decimal("1") + (markup_percent / Decimal("100")))
        steps = (price / Decimal("10")).to_integral_value(rounding=ROUND_UP)
        return (steps * Decimal("10")).quantize(Decimal("0.01"))


class PriceList(models.Model):
    """
    Прайс-лист: название, тип цен (база для расчёта), колонки с скидкой/наценкой.
    Позиции заполняются вручную или из номенклатуры/остатков.
    """
    BASE_PURCHASE = "purchase"
    BASE_PLANNED = "planned"
    BASE_MIN = "min"
    BASE_CHOICES = [
        (BASE_PURCHASE, "Закупочная цена"),
        (BASE_PLANNED, "Плановая цена продажи"),
        (BASE_MIN, "Минимальная цена"),
    ]

    name = models.CharField("Название прайс-листа", max_length=255)
    base_price_type = models.CharField(
        "Тип цен (база для расчёта)",
        max_length=20,
        choices=BASE_CHOICES,
        default=BASE_PLANNED,
    )
    comment = models.TextField("Комментарий", blank=True)
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)
    updated_at = models.DateTimeField("Дата изменения", auto_now=True)

    class Meta:
        verbose_name = "Прайс-лист"
        verbose_name_plural = "Прайс-листы"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name


class PriceListColumn(models.Model):
    """Колонка прайс-листа: название, скидка/наценка в % от цены продажи."""
    price_list = models.ForeignKey(
        PriceList,
        verbose_name="Прайс-лист",
        on_delete=models.CASCADE,
        related_name="columns",
    )
    name = models.CharField("Название колонки", max_length=255)
    order = models.PositiveSmallIntegerField("Порядок", default=1)
    discount_markup_percent = models.DecimalField(
        "Скидка (-) или наценка (+), %",
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Положительное — наценка, отрицательное — скидка. Пусто — без изменения.",
    )
    use_percent = models.BooleanField(
        "Скидка/наценка % от цены продажи",
        default=True,
        help_text="Если снять — колонка без цен, заполняется вручную.",
    )

    class Meta:
        verbose_name = "Колонка прайс-листа"
        verbose_name_plural = "Колонки прайс-листа"
        ordering = ["price_list", "order", "pk"]

    def __str__(self) -> str:
        return self.name


class PriceListEntry(models.Model):
    """Ячейка прайс-листа: товар, колонка, цена."""
    price_list = models.ForeignKey(
        PriceList,
        verbose_name="Прайс-лист",
        on_delete=models.CASCADE,
        related_name="entries",
    )
    product = models.ForeignKey(
        Product,
        verbose_name="Товар",
        on_delete=models.CASCADE,
        related_name="price_list_entries",
    )
    column = models.ForeignKey(
        PriceListColumn,
        verbose_name="Колонка",
        on_delete=models.CASCADE,
        related_name="entries",
    )
    price = models.DecimalField(
        "Цена",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Позиция прайс-листа"
        verbose_name_plural = "Позиции прайс-листа"
        unique_together = ("price_list", "product", "column")
        ordering = ["price_list", "product__name", "column__order"]

    def __str__(self) -> str:
        return f"{self.price_list}: {self.product} — {self.column} = {self.price}"


class TechCard(models.Model):
    """
    Технологическая карта — описывает состав изделия (комплектующие, сырьё, материалы).
    Может использоваться при базовом и расширенном способе производства.
    """
    name = models.CharField("Наименование", max_length=255)
    tech_process = models.ForeignKey(
        "TechProcess",
        verbose_name="Техпроцесс",
        on_delete=models.PROTECT,
        related_name="tech_cards",
    )
    product = models.ForeignKey(
        Product,
        verbose_name="Изделие",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tech_cards",
        help_text="Изделие, для которого составлена карта (необязательно). При сохранении техкарты нормы "
        "позиций «материал» копируются в карточку изделия для расчёта себестоимости. Если техкарт несколько, "
        "в карточке товара остаются нормы из последней сохранённой карты с этим изделием.",
    )
    card_group = models.ForeignKey(
        ProductGroup,
        verbose_name="Группа техкарты",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tech_cards",
    )
    allocate_cost = models.BooleanField(
        "Распределять себестоимость",
        null=True,
        blank=True,
    )
    description = models.TextField("Описание", blank=True)
    LABOR_NORM_INPUT_HOURS = "hours"
    LABOR_NORM_INPUT_MINUTES = "minutes"
    LABOR_NORM_INPUT_CHOICES = [
        (LABOR_NORM_INPUT_HOURS, "Нормо-часы"),
        (LABOR_NORM_INPUT_MINUTES, "Минуты"),
    ]
    labor_norm_input_unit = models.CharField(
        "Ввод нормы времени",
        max_length=16,
        choices=LABOR_NORM_INPUT_CHOICES,
        default=LABOR_NORM_INPUT_HOURS,
        help_text="В разделе «Деньги»: вводить норму по этапам в часах или в минутах. В расчётах всегда используются нормо-часы.",
    )

    class Meta:
        verbose_name = "Технологическая карта"
        verbose_name_plural = "Технологические карты"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def planned_cut_cost_per_unit(self) -> Decimal:
        """Плановые затраты на рез по метрам на 1 изделие по этой техкарте (сумма по строкам с нормой м и ставкой этапа)."""
        total = Decimal("0")
        for item in self.items.select_related("production_stage"):
            L = item.cut_length_meters_per_unit
            if L is None or L <= 0:
                continue
            st = item.production_stage
            if not st:
                continue
            r = st.cut_rate_per_meter
            if r is None or r <= 0:
                continue
            total += Decimal(str(L)) * Decimal(str(r))
        return total.quantize(Decimal("0.01"))

    def planned_labor_cost_per_unit(self) -> Decimal:
        """
        Оплата на 1 изд.: сумма по строкам «Деньги»
        (время станка/этапа + труд сотрудника);
        если строк нет — по нормам времени карточки изделия.
        """
        if self.pk:
            total = Decimal("0")
            for line in self.labor_lines.select_related("production_stage"):
                total += line.total_pay_per_unit()
            if total > 0 or self.labor_lines.exists():
                return total.quantize(Decimal("0.01"))
        if not self.product_id:
            return Decimal("0")
        total = Decimal("0")
        for norm in self.product.labor_norms.select_related("operation_type"):
            hours = Decimal(str(norm.minutes_per_unit or 0)) / Decimal("60")
            rate = Decimal(str(norm.operation_type.hourly_rate or 0))
            total += hours * rate
        return total.quantize(Decimal("0.01"))

    def planned_overhead_per_unit(self) -> Decimal:
        if not self.pk:
            return Decimal("0")
        from django.db.models import Sum

        s = self.labor_lines.aggregate(s=Sum("overhead_per_unit"))["s"]
        if s is None:
            return Decimal("0")
        return Decimal(str(s)).quantize(Decimal("0.01"))

    def planned_material_cost_per_unit(self) -> Decimal:
        """Материалы на 1 изд. по строкам техкарты × средняя цена закупки."""
        total = Decimal("0")
        for item in self.items.filter(
            material__isnull=False,
            item_kind__in=(TechCardItem.KIND_RAW, TechCardItem.KIND_MATERIAL),
        ).select_related("material"):
            price = item.material.average_price
            if price is None:
                continue
            total += Decimal(str(price)) * Decimal(str(item.quantity))
        return total.quantize(Decimal("0.01"))

    def planned_total_cost_per_unit(self) -> Decimal:
        """Плановая себестоимость 1 изделия по техкарте: материалы + труд + прочее + рез."""
        return (
            self.planned_material_cost_per_unit()
            + self.planned_labor_cost_per_unit()
            + self.planned_overhead_per_unit()
            + self.planned_cut_cost_per_unit()
        ).quantize(Decimal("0.01"))

    def material_quantities_per_unit_by_material_id(self) -> dict[int, Decimal]:
        """Суммарный расход материала на 1 готовое изделие по всем строкам техкарты (с материалом)."""
        from collections import defaultdict

        out: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
        for item in self.items.filter(material__isnull=False):
            out[item.material_id] += item.quantity
        return dict(out)

    def sync_material_norms_to_product(self) -> None:
        """
        Копирует нормы расхода из позиций техкарты с заполненным «материал» в ProductMaterial
        выбранного изделия (плановая себестоимость, вкладка «Стоимость»). Полуфабрикаты
        (позиции с изделием) не переносятся. Несколько строк с одним материалом суммируются.
        """
        if not self.product_id:
            return
        from django.db import transaction

        agg = self.material_quantities_per_unit_by_material_id()
        with transaction.atomic():
            ProductMaterial.objects.filter(product_id=self.product_id).delete()
            if not agg:
                return
            ProductMaterial.objects.bulk_create(
                [
                    ProductMaterial(
                        product_id=self.product_id,
                        material_id=mid,
                        quantity_per_unit=qty,
                    )
                    for mid, qty in sorted(agg.items(), key=lambda x: x[0])
                ]
            )


class TechCardItem(models.Model):
    """
    Позиция состава технологической карты: материал либо полуфабрикат/изделие.
    Полуфабрикат — изделие в составе другой техкарты (комплектующее).
    """
    KIND_COMPONENT = "component"
    KIND_RAW = "raw"
    KIND_MATERIAL = "material"

    KIND_CHOICES = [
        (KIND_COMPONENT, "Комплектующие / полуфабрикат"),
        (KIND_RAW, "Сырьё"),
        (KIND_MATERIAL, "Материал"),
    ]

    tech_card = models.ForeignKey(
        TechCard,
        verbose_name="Технологическая карта",
        on_delete=models.CASCADE,
        related_name="items",
    )
    material = models.ForeignKey(
        Material,
        verbose_name="Материал",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tech_card_items_as_material",
    )
    product = models.ForeignKey(
        "Product",
        verbose_name="Полуфабрикат / изделие",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tech_card_items_as_component",
        help_text="Изделие (полуфабрикат), расходуемое по норме на единицу",
    )
    quantity = models.DecimalField(
        "Количество на единицу",
        max_digits=12,
        decimal_places=4,
        help_text="Норма расхода на одно изделие. Один и тот же материал в нескольких строках (разные этапы) "
        "суммируется при резерве и списании. Один физический лист на два этапа: одна строка с количеством 1, "
        "на втором этапе лист не дублируйте (или 0); расходники (диск) — отдельными строками по этапам.",
    )
    item_kind = models.CharField(
        "Тип позиции",
        max_length=20,
        choices=KIND_CHOICES,
        default=KIND_MATERIAL,
    )
    production_stage = models.ForeignKey(
        "ProductionStage",
        verbose_name="Этап",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tech_card_items",
    )
    cut_length_meters_per_unit = models.DecimalField(
        "Норма длины реза на 1 изд., м",
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Погонные метры реза на одно изделие (лазер и т.п.). Учитывается, если у выбранного этапа задана «Стоимость метра реза».",
    )
    note = models.CharField("Примечание", max_length=255, blank=True)
    composition_order = models.PositiveIntegerField(
        "Порядок в списке комплектующих",
        default=0,
        db_index=True,
        help_text="Для сортировки строк «Продукция» на техкарте; материалы не затрагиваются.",
    )
    component_tech_card = models.ForeignKey(
        "TechCard",
        verbose_name="Техкарта полуфабриката",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="referenced_by_component_items",
        help_text="Техкарта изготовления полуфабриката (для позиций с типом «Комплектующие»).",
    )

    class Meta:
        verbose_name = "Позиция технологической карты"
        verbose_name_plural = "Позиции технологической карты"
        ordering = ["item_kind", "composition_order", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=("tech_card", "product"),
                condition=Q(product__isnull=False),
                name="core_techcarditem_tech_card_product_uniq",
            ),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        if bool(self.material_id) == bool(self.product_id):
            raise ValidationError("Укажите либо материал, либо полуфабрикат (изделие).")

        if self.component_tech_card_id:
            if self.item_kind != self.KIND_COMPONENT or not self.product_id:
                raise ValidationError(
                    {
                        "component_tech_card": "Техкарту полуфабриката можно указать только для позиции с изделием (комплектующее).",
                    }
                )
            ctc = self.component_tech_card
            if ctc and ctc.product_id != self.product_id:
                raise ValidationError(
                    {
                        "component_tech_card": "Выбранная техкарта должна относиться к тому же изделию, что и позиция.",
                    }
                )

        if self.production_stage_id and self.tech_card_id:
            tc = self.tech_card
            tid = getattr(tc, "tech_process_id", None)
            if tid and not TechProcessStage.objects.filter(
                tech_process_id=tid,
                production_stage_id=self.production_stage_id,
            ).exists():
                raise ValidationError(
                    {
                        "production_stage": "Этап не входит в техпроцесс, выбранный в карте.",
                    }
                )

        cl = self.cut_length_meters_per_unit
        if cl is not None and cl > 0:
            if not self.production_stage_id:
                raise ValidationError(
                    {
                        "cut_length_meters_per_unit": "Для нормы реза укажите этап (у этапа задаётся ₽/м).",
                    }
                )
            st = self.production_stage
            rate = st.cut_rate_per_meter if st else None
            if rate is None or rate <= 0:
                raise ValidationError(
                    {
                        "cut_length_meters_per_unit": f"У этапа «{st}» не задана стоимость метра реза в справочнике этапов.",
                    }
                )

    def __str__(self) -> str:
        if self.product_id:
            return f"{self.tech_card} — {self.get_item_kind_display()}: {self.product}"
        return f"{self.tech_card} — {self.get_item_kind_display()}: {self.material}"


class TechCardLaborLine(models.Model):
    """
    Норма времени и прочие затраты по этапу (вкладка «Деньги» техкарты).
    Стоимость нормо-часа подставляется из справочника этапа (ProductionStage.hourly_rate).
    """

    tech_card = models.ForeignKey(
        TechCard,
        verbose_name="Технологическая карта",
        on_delete=models.CASCADE,
        related_name="labor_lines",
    )
    production_stage = models.ForeignKey(
        "ProductionStage",
        verbose_name="Этап",
        on_delete=models.PROTECT,
        related_name="tech_card_labor_lines",
        help_text="Стоимость нормо-часа подставляется из справочника этапа.",
    )
    norm_hours = models.DecimalField(
        "Нормо-часы",
        max_digits=12,
        decimal_places=4,
        default=0,
        help_text=(
            "Время работы станка/этапа на 1 шт. В эту ставку обычно включают амортизацию, "
            "электричество и обслуживание оборудования."
        ),
    )
    employee_minutes = models.DecimalField(
        "Время сотрудника, мин",
        max_digits=12,
        decimal_places=2,
        default=0,
        blank=True,
        help_text=(
            "Сколько минут сотрудник занят на 1 шт.: подготовка макета, настройка станка, "
            "укладка материала, контроль, снятие детали, чистка."
        ),
    )
    overhead_per_unit = models.DecimalField(
        "Затраты на производство",
        max_digits=12,
        decimal_places=2,
        default=0,
        blank=True,
        help_text="Прочие затраты на 1 шт. по этапу, ₽.",
    )

    class Meta:
        verbose_name = "Норма времени по этапу (деньги)"
        verbose_name_plural = "Нормы времени и деньги по этапам"
        unique_together = ("tech_card", "production_stage")

    def __str__(self) -> str:
        return f"{self.tech_card}: {self.production_stage}"

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.tech_card_id and self.production_stage_id and self.tech_card.tech_process_id:
            if not TechProcessStage.objects.filter(
                tech_process_id=self.tech_card.tech_process_id,
                production_stage_id=self.production_stage_id,
            ).exists():
                raise ValidationError(
                    {"production_stage": "Этап не входит в техпроцесс, выбранный в карте."}
                )

    def machine_pay_per_unit(self) -> Decimal:
        st = self.production_stage
        rate = st.hourly_rate if st else None
        if rate is None:
            rate = Decimal("0")
        nh = self.norm_hours if self.norm_hours is not None else Decimal("0")
        return (nh * Decimal(str(rate))).quantize(Decimal("0.01"))

    def employee_pay_per_unit(self) -> Decimal:
        minutes = self.employee_minutes if self.employee_minutes is not None else Decimal("0")
        rate = self.employee_hourly_rate_for_plan()
        hours = Decimal(str(minutes)) / Decimal("60")
        return (hours * Decimal(str(rate))).quantize(Decimal("0.01"))

    def employee_hourly_rate_for_plan(self) -> Decimal:
        stage = self.production_stage
        if not stage:
            return Decimal("0")
        return stage.employee_hourly_rate_for_plan()

    def total_pay_per_unit(self) -> Decimal:
        return (self.machine_pay_per_unit() + self.employee_pay_per_unit()).quantize(Decimal("0.01"))

    def labor_pay_per_unit(self) -> Decimal:
        """Совместимость со старым названием: теперь это общий итог станок + сотрудник."""
        return self.total_pay_per_unit()


class Organization(models.Model):
    """Организация (юридическое лицо или ИП). Реквизиты можно подставить из базы ФНС по ИНН."""
    name = models.CharField("Название", max_length=255)
    inn = models.CharField("ИНН", max_length=12, blank=True)
    kpp = models.CharField("КПП", max_length=9, blank=True, help_text="Только для ЮЛ")
    ogrn = models.CharField("ОГРН / ОГРНИП", max_length=15, blank=True)
    legal_address = models.TextField("Юридический адрес", blank=True)
    is_individual = models.BooleanField(
        "Индивидуальный предприниматель",
        default=False,
        help_text="ИП (иначе — юридическое лицо)",
    )
    is_supplier = models.BooleanField(
        "Поставщик",
        default=True,
        help_text="Роль в закупках: поставщик номенклатуры, приёмки, счетов от поставщика.",
    )
    is_buyer = models.BooleanField(
        "Покупатель",
        default=True,
        help_text="Роль в продажах: клиент по заказам покупателей (при появлении привязки к контрагенту).",
    )
    phone = models.CharField("Телефон", max_length=64, blank=True)
    email = models.EmailField("Email", blank=True)
    general_director = models.CharField("Генеральный директор", max_length=255, blank=True)
    signer_name = models.CharField("Подписант (ФИО)", max_length=255, blank=True)
    signer_position = models.CharField("Должность подписанта", max_length=255, blank=True)
    signer_authority = models.CharField(
        "Основание полномочий",
        max_length=255,
        blank=True,
        help_text="Например: Устав, доверенность №... от ...",
    )
    bank_account = models.CharField("Расчётный счёт", max_length=64, blank=True)
    bank_name = models.CharField("Банк", max_length=255, blank=True)
    bank_bik = models.CharField("БИК", max_length=20, blank=True)
    bank_corr_account = models.CharField("Корреспондентский счёт", max_length=64, blank=True)
    fns_status = models.CharField("Статус по ФНС", max_length=255, blank=True)
    fns_raw_data = models.JSONField("Данные ФНС (raw)", default=dict, blank=True)
    fns_updated_at = models.DateTimeField("Обновлено из ФНС", null=True, blank=True)

    class Meta:
        verbose_name = "Контрагент"
        verbose_name_plural = "Контрагенты"
        ordering = ["name"]

    def clean(self):
        super().clean()
        if not self.is_supplier and not self.is_buyer:
            raise ValidationError(
                "Укажите хотя бы одну роль: «Поставщик» или «Покупатель»."
            )

    def __str__(self) -> str:
        return self.name


class ExpenseLedgerEntry(Organization):
    """
    Виртуальный журнал расходов для блока «Бухгалтерия».
    Данные берутся агрегированно из документов закупок (без отдельной таблицы).
    """

    class Meta:
        proxy = True
        verbose_name = "Расход"
        verbose_name_plural = "Расходы"


class Contract(models.Model):
    TYPE_SUPPLIER = "supplier"
    TYPE_CUSTOMER = "customer"
    TYPE_CHOICES = [
        (TYPE_SUPPLIER, "Договор с поставщиком"),
        (TYPE_CUSTOMER, "Договор с клиентом"),
    ]

    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_EXPIRED = "expired"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_ACTIVE, "Действует"),
        (STATUS_EXPIRED, "Истёк"),
        (STATUS_CANCELLED, "Расторгнут"),
    ]

    number = models.CharField("Номер договора", max_length=64)
    contract_date = models.DateField("Дата договора")
    valid_until = models.DateField("Действует до", null=True, blank=True)
    contract_type = models.CharField("Тип договора", max_length=20, choices=TYPE_CHOICES)
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    our_organization = models.ForeignKey(
        Organization,
        verbose_name="Наша организация",
        on_delete=models.PROTECT,
        related_name="contracts_as_our_side",
    )
    counterparty = models.ForeignKey(
        Organization,
        verbose_name="Контрагент",
        on_delete=models.PROTECT,
        related_name="contracts_as_counterparty",
    )
    payment_terms = models.TextField("Условия оплаты", blank=True)
    delivery_terms = models.TextField("Условия поставки/оказания", blank=True)
    subject = models.TextField("Предмет договора", blank=True)
    amount_limit = models.DecimalField(
        "Лимит суммы",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    comment = models.TextField("Комментарий", blank=True)
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)
    updated_at = models.DateTimeField("Дата изменения", auto_now=True)

    class Meta:
        verbose_name = "Договор"
        verbose_name_plural = "Договоры"
        ordering = ["-contract_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["number", "our_organization", "counterparty"],
                name="uniq_contract_number_per_pair",
            )
        ]

    def __str__(self) -> str:
        return f"{self.number} ({self.get_contract_type_display()})"

    def is_active_on(self, dt):
        if self.status != self.STATUS_ACTIVE:
            return False
        if self.valid_until and dt and dt > self.valid_until:
            return False
        return True


class ContractVersion(models.Model):
    contract = models.ForeignKey(
        Contract,
        verbose_name="Договор",
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField("Версия", default=1)
    generated_text = models.TextField("Текст версии", blank=True)
    generated_file = models.FileField(
        "Файл версии",
        upload_to="contracts/generated/",
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Кем создано",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contract_versions",
    )
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)

    class Meta:
        verbose_name = "Версия договора"
        verbose_name_plural = "Версии договоров"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "version_number"],
                name="uniq_contract_version_number",
            )
        ]

    def __str__(self) -> str:
        return f"{self.contract.number} v{self.version_number}"


class Warehouse(models.Model):
    """Склад для хранения материалов и продукции."""
    name = models.CharField("Название", max_length=255)
    organization = models.ForeignKey(
        Organization,
        verbose_name="Организация",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="warehouses",
    )

    class Meta:
        verbose_name = "Склад"
        verbose_name_plural = "Склады"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class MaterialStock(models.Model):
    """Остаток материала на складе."""
    warehouse = models.ForeignKey(
        Warehouse,
        verbose_name="Склад",
        on_delete=models.CASCADE,
        related_name="material_stocks",
    )
    material = models.ForeignKey(
        Material,
        verbose_name="Материал",
        on_delete=models.CASCADE,
        related_name="warehouse_stocks",
    )
    quantity = models.DecimalField("Количество", max_digits=12, decimal_places=3, default=0)

    class Meta:
        verbose_name = "Остаток материала на складе"
        verbose_name_plural = "Остатки материалов на складах"
        unique_together = ("warehouse", "material")
        ordering = ["warehouse", "material__name"]

    def __str__(self) -> str:
        return f"{self.warehouse}: {self.material} — {self.quantity}"


class ProductStock(models.Model):
    """Остаток продукции на складе."""
    warehouse = models.ForeignKey(
        Warehouse,
        verbose_name="Склад",
        on_delete=models.CASCADE,
        related_name="product_stocks",
    )
    product = models.ForeignKey(
        Product,
        verbose_name="Изделие",
        on_delete=models.CASCADE,
        related_name="warehouse_stocks",
    )
    quantity = models.DecimalField("Количество", max_digits=12, decimal_places=3, default=0)

    class Meta:
        verbose_name = "Остаток продукции на складе"
        verbose_name_plural = "Остатки продукции на складах"
        unique_together = ("warehouse", "product")
        ordering = ["warehouse", "product__name"]

    def __str__(self) -> str:
        return f"{self.warehouse}: {self.product} — {self.quantity}"


class TechOperation(models.Model):
    """
    Технологическая операция — документ для регистрации сборочных и производственных операций.
    При проведении: материалы списываются со склада материалов, продукция оприходуется на склад продукции.
    """
    STATUS_DRAFT = "draft"
    STATUS_COMPLETED = "completed"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_COMPLETED, "Проведён"),
    ]

    organization = models.ForeignKey(
        Organization,
        verbose_name="Организация",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tech_operations",
    )
    product_warehouse = models.ForeignKey(
        Warehouse,
        verbose_name="Склад для продукции",
        on_delete=models.PROTECT,
        related_name="tech_ops_product",
    )
    material_warehouse = models.ForeignKey(
        Warehouse,
        verbose_name="Склад для материалов",
        on_delete=models.PROTECT,
        related_name="tech_ops_material",
    )
    tech_card = models.ForeignKey(
        TechCard,
        verbose_name="Техкарта",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tech_operations",
        help_text="Заполнить состав из техкарты или ввести вручную",
    )
    production_order = models.ForeignKey(
        "ProductionOrder",
        verbose_name="Заказ на производство",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tech_operations",
    )
    production_assignment_item = models.ForeignKey(
        "ProductionAssignmentItem",
        verbose_name="Позиция производственного задания",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tech_operations",
    )
    status = models.CharField(
        "Статус",
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )
    production_cost = models.DecimalField(
        "Затраты на производство",
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Дополнительные затраты (труд, энергия и т.п.), включаются в себестоимость",
    )
    date = models.DateField("Дата", null=True, blank=True)
    comment = models.TextField("Комментарий", blank=True)
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)

    class Meta:
        verbose_name = "Технологическая операция"
        verbose_name_plural = "Технологические операции"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Техоперация #{self.pk} от {self.date or self.created_at.date()}"

    def get_materials_total_cost(self) -> Decimal:
        """Сумма себестоимости списываемых материалов (по средней цене)."""
        total = Decimal("0")
        for item in self.materials.select_related("material"):
            price = item.material.average_price
            if price is not None:
                total += item.quantity * price
        return total.quantize(Decimal("0.01"))

    def get_total_cost(self) -> Decimal:
        """Себестоимость: материалы + затраты на производство."""
        return (self.get_materials_total_cost() + (self.production_cost or 0)).quantize(Decimal("0.01"))

    def fill_from_tech_card(self, production_quantity: Decimal) -> None:
        """Заполнить продукцию и материалы из техкарты с заданным объёмом производства."""
        if not self.tech_card:
            return
        self.products.all().delete()
        self.materials.all().delete()
        if self.tech_card.product_id:
            TechOperationProduct.objects.create(
                tech_operation=self,
                product=self.tech_card.product,
                quantity=production_quantity,
            )
        # Полуфабрикаты (item.product) списываются при проведении по техкарте
        for mid, q_per_unit in self.tech_card.material_quantities_per_unit_by_material_id().items():
            TechOperationMaterial.objects.create(
                tech_operation=self,
                material_id=mid,
                quantity=q_per_unit * production_quantity,
            )

    def conduct(self) -> None:
        """Провести операцию: списать материалы и полуфабрикаты, оприходовать продукцию."""
        if self.status == self.STATUS_COMPLETED:
            return
        from django.utils import timezone
        from core.services.production_conduct import consume_material, consume_product, produce_product

        for item in self.materials.select_related("material"):
            consume_material(
                warehouse=self.material_warehouse,
                material_id=item.material_id,
                quantity=item.quantity,
                material_name=item.material.name,
            )
        # Списание полуфабрикатов по техкарте (со склада продукции)
        if self.tech_card_id:
            production_qty = sum(p.quantity for p in self.products.all()) or Decimal("0")
            for tc_item in self.tech_card.items.select_related("product").filter(product__isnull=False):
                need = tc_item.quantity * production_qty
                consume_product(
                    warehouse=self.product_warehouse,
                    product_id=tc_item.product_id,
                    quantity=need,
                    product_name=tc_item.product.name,
                )
        for item in self.products.select_related("product"):
            produce_product(
                warehouse=self.product_warehouse,
                product_id=item.product_id,
                quantity=item.quantity,
            )
        self.status = self.STATUS_COMPLETED
        if not self.date:
            self.date = timezone.now().date()
        self.save(update_fields=["status", "date"])
        # Если техоперация привязана к заказу на производство — снять резерв и отметить заказ выполненным
        if self.production_order_id:
            self.production_order.release_reservation()
            self.production_order.status = ProductionOrder.STATUS_COMPLETED
            self.production_order.save(update_fields=["status"])


class TechOperationProduct(models.Model):
    """Позиция технологической операции: производимая продукция."""
    tech_operation = models.ForeignKey(
        TechOperation,
        verbose_name="Технологическая операция",
        on_delete=models.CASCADE,
        related_name="products",
    )
    product = models.ForeignKey(
        Product,
        verbose_name="Изделие",
        on_delete=models.PROTECT,
    )
    quantity = models.DecimalField("Количество", max_digits=12, decimal_places=4)

    class Meta:
        verbose_name = "Продукция техоперации"
        verbose_name_plural = "Продукция техопераций"

    def __str__(self) -> str:
        return f"{self.tech_operation}: {self.product} × {self.quantity}"


class TechOperationMaterial(models.Model):
    """Позиция технологической операции: списываемый материал."""
    tech_operation = models.ForeignKey(
        TechOperation,
        verbose_name="Технологическая операция",
        on_delete=models.CASCADE,
        related_name="materials",
    )
    material = models.ForeignKey(
        Material,
        verbose_name="Материал",
        on_delete=models.PROTECT,
    )
    quantity = models.DecimalField("Количество", max_digits=12, decimal_places=4)

    class Meta:
        verbose_name = "Материал техоперации"
        verbose_name_plural = "Материалы техопераций"
        unique_together = ("tech_operation", "material")

    def __str__(self) -> str:
        return f"{self.tech_operation}: {self.material} × {self.quantity}"


class ProductDisassembly(models.Model):
    """
    Разбор изделия — возврат комплектующих на склад по техкарте.
    При проведении: продукция списывается со склада продукции,
    материалы (по составу техкарты) оприходуются на склад материалов.
    """
    STATUS_DRAFT = "draft"
    STATUS_COMPLETED = "completed"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_COMPLETED, "Проведён"),
    ]

    tech_card = models.ForeignKey(
        TechCard,
        verbose_name="Техкарта",
        on_delete=models.PROTECT,
        related_name="disassemblies",
        help_text="Состав разбора берётся из техкарты изделия",
    )
    quantity = models.DecimalField(
        "Количество к разбору",
        max_digits=12,
        decimal_places=4,
    )
    product_warehouse = models.ForeignKey(
        Warehouse,
        verbose_name="Склад продукции (откуда)",
        on_delete=models.PROTECT,
        related_name="disassemblies_from",
    )
    material_warehouse = models.ForeignKey(
        Warehouse,
        verbose_name="Склад материалов (куда)",
        on_delete=models.PROTECT,
        related_name="disassemblies_to",
    )
    status = models.CharField(
        "Статус",
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )
    date = models.DateField("Дата", null=True, blank=True)
    comment = models.TextField("Комментарий", blank=True)
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)

    class Meta:
        verbose_name = "Разбор изделия"
        verbose_name_plural = "Разбор изделий"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Разбор #{self.pk} ({self.tech_card}) × {self.quantity}"

    def conduct(self) -> None:
        """Провести разбор: списать продукцию, оприходовать комплектующие на склад."""
        from django.utils import timezone
        from core.services.production_conduct import consume_product, produce_material

        if self.status == self.STATUS_COMPLETED:
            return
        if not self.tech_card.product_id:
            raise ValueError("У техкарты не указано изделие для разбора.")
        product = self.tech_card.product
        # Списываем продукцию
        consume_product(
            warehouse=self.product_warehouse,
            product_id=product.pk,
            quantity=self.quantity,
            product_name=product.name,
            item_label="изделия",
        )
        # Оприходуем материалы по техкарте (полуфабрикаты при разборе не возвращаем); нормы по материалу суммируются
        for mid, q_per_unit in self.tech_card.material_quantities_per_unit_by_material_id().items():
            qty_in = q_per_unit * self.quantity
            produce_material(
                warehouse=self.material_warehouse,
                material_id=mid,
                quantity=qty_in,
            )
        self.status = self.STATUS_COMPLETED
        if not self.date:
            self.date = timezone.now().date()
        self.save(update_fields=["status", "date"])


class ProductMaterial(models.Model):
    product = models.ForeignKey(
        Product,
        verbose_name="Изделие",
        on_delete=models.CASCADE,
        related_name="materials",
    )
    material = models.ForeignKey(Material, verbose_name="Материал", on_delete=models.CASCADE)
    quantity_per_unit = models.DecimalField(
        "Расход на 1 изделие",
        max_digits=12,
        decimal_places=4,
        help_text="Норма расхода материала на 1 изделие",
    )

    class Meta:
        verbose_name = "Материал изделия"
        verbose_name_plural = "Материалы изделия"
        unique_together = ("product", "material")

    def __str__(self) -> str:
        return f"{self.product} - {self.material}"


class OperationType(models.Model):
    name = models.CharField("Название операции", max_length=100)
    result_adjective = models.CharField(
        "Прилагательное для наименования товара",
        max_length=100,
        blank=True,
        help_text="Например: шлифованный. Пусто — из названия (шлифование → шлифованный).",
    )
    description = models.TextField("Описание", blank=True)
    hourly_rate = models.DecimalField(
        "Ставка за час",
        max_digits=10,
        decimal_places=2,
        default=0,
        blank=True,
        help_text="Ставка за час работы для этого типа операции",
    )

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name = "Тип операции"
        verbose_name_plural = "Типы операций"


class ProductLabor(models.Model):
    product = models.ForeignKey(
        Product,
        verbose_name="Изделие",
        on_delete=models.CASCADE,
        related_name="labor_norms",
    )
    operation_type = models.ForeignKey(
        OperationType,
        verbose_name="Тип операции",
        on_delete=models.CASCADE,
    )
    minutes_per_unit = models.DecimalField(
        "Время на 1 изделие (мин)",
        max_digits=8,
        decimal_places=2,
        help_text="Норма времени (в минутах) на 1 изделие",
    )

    class Meta:
        verbose_name = "Норма времени по операции"
        verbose_name_plural = "Нормы времени по операциям"
        unique_together = ("product", "operation_type")

    def __str__(self) -> str:
        return f"{self.product} - {self.operation_type}"


class Employee(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="Пользователь",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee",
        help_text="Для входа в веб-приложение и просмотра своей работы и зарплаты",
    )
    full_name = models.CharField("ФИО", max_length=255)
    position = models.CharField("Должность", max_length=100, blank=True)
    hourly_rate = models.DecimalField(
        "Часовая ставка",
        max_digits=10,
        decimal_places=2,
        help_text="Ставка за час работы сотрудника",
    )

    def __str__(self) -> str:
        return self.full_name

    class Meta:
        verbose_name = "Сотрудник"
        verbose_name_plural = "Сотрудники"


class Order(models.Model):
    STATUS_NEW = "NEW"
    STATUS_IN_PROGRESS = "INP"
    STATUS_DONE = "DON"
    STATUS_CANCELLED = "CNL"

    STATUS_CHOICES = [
        (STATUS_NEW, "Новый"),
        (STATUS_IN_PROGRESS, "В работе"),
        (STATUS_DONE, "Завершен"),
        (STATUS_CANCELLED, "Отменен"),
    ]

    customer_name = models.CharField(
        "Клиент",
        max_length=255,
        help_text="Имя или название клиента",
    )
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)
    status = models.CharField("Статус", max_length=3, choices=STATUS_CHOICES, default=STATUS_NEW)
    comment = models.TextField("Комментарий", blank=True)

    class Meta:
        verbose_name = "Заказ покупателя"
        verbose_name_plural = "Заказы покупателей"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Заказ покупателя №{self.pk} — {self.customer_name}"


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        verbose_name="Заказ покупателя",
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(Product, verbose_name="Изделие", on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField("Количество")
    planned_price = models.DecimalField(
        "Цена продажи за единицу",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Цена продажи за единицу (может отличаться от плановой в карточке изделия)",
    )

    def __str__(self) -> str:
        return f"{self.order} - {self.product} x {self.quantity}"

    class Meta:
        verbose_name = "Позиция заказа покупателя"
        verbose_name_plural = "Позиции заказа покупателя"

    def save(self, *args, **kwargs):
        # Если цену в заказе не ввели вручную, подставляем её автоматически:
        # 1) из плановой цены изделия (если задана),
        # 2) иначе быстрый расчёт: себестоимость + наценка + округление.
        if self.planned_price in (None, "") and self.product_id:
            product = self.product
            if product.planned_price is not None:
                self.planned_price = product.planned_price
            else:
                self.planned_price = product.get_quick_sale_price()
        super().save(*args, **kwargs)


class CustomerInvoice(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_SENT = "sent"
    STATUS_PAID = "paid"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_SENT, "Отправлен клиенту"),
        (STATUS_PAID, "Оплачен"),
        (STATUS_CANCELLED, "Отменён"),
    ]

    number = models.CharField("Номер счёта", max_length=32, unique=True, blank=True)
    production_request = models.ForeignKey(
        "ProductionRequest",
        verbose_name="Запрос на производство",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_invoices",
    )
    order = models.ForeignKey(
        Order,
        verbose_name="Заказ покупателя",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_invoices",
    )
    customer_name = models.CharField("Клиент", max_length=255)
    customer_email = models.EmailField("Email клиента", blank=True)
    customer_phone = models.CharField("Телефон клиента", max_length=64, blank=True)
    our_organization = models.ForeignKey(
        "Organization",
        verbose_name="Наша организация",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_customer_invoices",
    )
    issue_date = models.DateField("Дата счёта", default=timezone.localdate)
    due_date = models.DateField("Оплатить до", null=True, blank=True)
    amount = models.DecimalField("Сумма", max_digits=14, decimal_places=2)
    purpose = models.TextField("Назначение платежа", blank=True)
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    sent_to_chat_at = models.DateTimeField("Отправлен клиенту в чат", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Создал",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_customer_invoices",
    )
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Счёт клиенту"
        verbose_name_plural = "Счета клиентам"
        ordering = ["-created_at", "-pk"]

    def __str__(self) -> str:
        return self.number or f"Счёт клиенту #{self.pk}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            n = f"СК-{self.pk:06d}"
            type(self).objects.filter(pk=self.pk).update(number=n)
            self.number = n


class BankPaymentOrder(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_SENT = "sent"
    STATUS_ACCEPTED = "accepted"
    STATUS_FAILED = "failed"
    STATUS_NOT_CONFIGURED = "not_configured"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_SENT, "Отправлено в банк"),
        (STATUS_ACCEPTED, "Принято банком"),
        (STATUS_FAILED, "Ошибка отправки"),
        (STATUS_NOT_CONFIGURED, "Интеграция не настроена"),
    ]

    number = models.CharField("Номер платежного поручения", max_length=32, unique=True, blank=True)
    customer_invoice = models.ForeignKey(
        CustomerInvoice,
        verbose_name="Счёт клиенту",
        on_delete=models.CASCADE,
        related_name="bank_payment_orders",
    )
    amount = models.DecimalField("Сумма", max_digits=14, decimal_places=2)
    payment_date = models.DateField("Дата платежа", auto_now_add=True)
    recipient_name = models.CharField("Получатель", max_length=255)
    recipient_inn = models.CharField("ИНН получателя", max_length=12, blank=True)
    recipient_account = models.CharField("Счёт получателя", max_length=64, blank=True)
    recipient_bank_name = models.CharField("Банк получателя", max_length=255, blank=True)
    recipient_bank_bik = models.CharField("БИК банка", max_length=20, blank=True)
    recipient_bank_corr_account = models.CharField("Корр. счёт банка", max_length=64, blank=True)
    purpose = models.TextField("Назначение платежа", blank=True)
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    external_operation_id = models.CharField("ID операции в банке", max_length=128, blank=True)
    payload = models.JSONField("Отправленный payload", default=dict, blank=True)
    bank_response = models.TextField("Ответ банка", blank=True)
    sent_at = models.DateTimeField("Отправлено в банк", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Создал",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_bank_payment_orders",
    )
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Платёжное поручение"
        verbose_name_plural = "Платёжные поручения"
        ordering = ["-created_at", "-pk"]

    def __str__(self) -> str:
        return self.number or f"Платёжное поручение #{self.pk}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            n = f"ПП-{self.pk:06d}"
            type(self).objects.filter(pk=self.pk).update(number=n)
            self.number = n


def _email_verification_token():
    return uuid4().hex


class EmailVerification(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="Пользователь",
        on_delete=models.CASCADE,
        related_name="email_verification",
    )
    token = models.CharField("Токен", max_length=64, unique=True, default=_email_verification_token)
    is_verified = models.BooleanField("Email подтверждён", default=False)
    sent_at = models.DateTimeField("Дата отправки", null=True, blank=True)
    verified_at = models.DateTimeField("Дата подтверждения", null=True, blank=True)
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)
    updated_at = models.DateTimeField("Дата изменения", auto_now=True)

    class Meta:
        verbose_name = "Подтверждение email"
        verbose_name_plural = "Подтверждения email"

    def __str__(self) -> str:
        state = "подтверждено" if self.is_verified else "ожидает подтверждения"
        return f"{self.user} — {state}"


class ProductionRequest(models.Model):
    STATUS_NEW = "new"
    STATUS_IN_REVIEW = "in_review"
    STATUS_QUOTED = "quoted"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CONVERTED = "converted"

    STATUS_CHOICES = [
        (STATUS_NEW, "Новая"),
        (STATUS_IN_REVIEW, "В обработке"),
        (STATUS_QUOTED, "Оценена"),
        (STATUS_APPROVED, "Согласована"),
        (STATUS_REJECTED, "Отклонена"),
        (STATUS_CONVERTED, "Конвертирована в заказ"),
    ]
    SCAN_PENDING = "pending"
    SCAN_CLEAN = "clean"
    SCAN_INFECTED = "infected"
    SCAN_FAILED = "failed"
    SCAN_SKIPPED = "skipped"
    SCAN_CHOICES = [
        (SCAN_PENDING, "Ожидает проверки"),
        (SCAN_CLEAN, "Проверен, угроз не найдено"),
        (SCAN_INFECTED, "Заблокирован: найдена угроза"),
        (SCAN_FAILED, "Ошибка проверки"),
        (SCAN_SKIPPED, "Проверка не выполнена"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Пользователь",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="production_requests",
    )
    customer_name = models.CharField("Клиент", max_length=255)
    phone = models.CharField("Телефон", max_length=64)
    email = models.EmailField("Email")
    request_title = models.CharField("Наименование заказа", max_length=255)
    product = models.ForeignKey(
        Product,
        verbose_name="Товар/основа",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="production_requests",
    )
    quantity = models.PositiveIntegerField("Количество", default=1)
    deadline = models.DateField("Желаемый срок", null=True, blank=True)
    layout_file = models.FileField(
        "Файл макета",
        upload_to="production_requests/layouts/",
        null=True,
        blank=True,
    )
    layout_scan_status = models.CharField(
        "Статус проверки файла",
        max_length=20,
        choices=SCAN_CHOICES,
        default=SCAN_PENDING,
    )
    layout_scan_result = models.TextField("Результат проверки файла", blank=True)
    layout_scanned_at = models.DateTimeField("Проверено в", null=True, blank=True)
    layout_is_quarantined = models.BooleanField("Файл в карантине", default=False)
    layout_quarantine_path = models.CharField("Путь в карантине", max_length=512, blank=True)
    specs = models.TextField("Параметры и требования", blank=True)
    material_preferences = models.CharField("Предпочтения по материалу", max_length=255, blank=True)
    comment = models.TextField("Комментарий клиента", blank=True)
    manager_comment = models.TextField("Комментарий менеджера", blank=True)
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW)
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)
    updated_at = models.DateTimeField("Дата изменения", auto_now=True)

    class Meta:
        verbose_name = "Запрос на производство"
        verbose_name_plural = "Запросы на производство"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Запрос #{self.pk} — {self.request_title}"


class ProductionRequestMessage(models.Model):
    production_request = models.ForeignKey(
        ProductionRequest,
        verbose_name="Запрос на производство",
        on_delete=models.CASCADE,
        related_name="messages",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Автор",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="production_request_messages",
    )
    is_employee_message = models.BooleanField("Сообщение сотрудника", default=False)
    text = models.TextField("Сообщение")
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)

    class Meta:
        verbose_name = "Сообщение по запросу на производство"
        verbose_name_plural = "Сообщения по запросам на производство"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Чат заявки #{self.production_request_id}"


# --- Базовый способ: заказ на производство (одна техкарта, резерв материалов) ---


class ProductionOrder(models.Model):
    """
    Заказ на производство — документ для планирования выпуска по одной техкарте.
    Позволяет зарезервировать материалы; выпуск оформляется техоперацией.
    """
    STATUS_DRAFT = "draft"
    STATUS_RESERVED = "reserved"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_RESERVED, "Материалы зарезервированы"),
        (STATUS_IN_PROGRESS, "В производстве"),
        (STATUS_COMPLETED, "Выполнен"),
        (STATUS_CANCELLED, "Отменён"),
    ]

    tech_card = models.ForeignKey(
        TechCard,
        verbose_name="Техкарта",
        on_delete=models.PROTECT,
        related_name="production_orders",
    )
    quantity = models.DecimalField(
        "Объём производства",
        max_digits=12,
        decimal_places=4,
        help_text="Количество по норме техкарты",
    )
    product_warehouse = models.ForeignKey(
        Warehouse,
        verbose_name="Склад для продукции",
        on_delete=models.PROTECT,
        related_name="production_orders_product",
    )
    material_warehouse = models.ForeignKey(
        Warehouse,
        verbose_name="Склад материалов",
        on_delete=models.PROTECT,
        related_name="production_orders_material",
    )
    status = models.CharField(
        "Статус",
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )
    date_planned = models.DateField("Плановая дата", null=True, blank=True)
    date_deadline = models.DateField("Срок выполнения", null=True, blank=True)
    comment = models.TextField("Комментарий", blank=True)
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)

    class Meta:
        verbose_name = "Заказ на производство"
        verbose_name_plural = "Заказы на производство"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Заказ на пр-во #{self.pk} ({self.tech_card}) × {self.quantity}"

    def get_required_materials(self):
        """Потребность в материалах по техкарте на объём quantity (только материалы)."""
        if not self.tech_card_id:
            return []
        agg = self.tech_card.material_quantities_per_unit_by_material_id()
        if not agg:
            return []
        mats = Material.objects.in_bulk(agg.keys())
        return [
            (mats[mid], q_per_unit * self.quantity)
            for mid, q_per_unit in sorted(agg.items(), key=lambda x: x[0])
            if mid in mats
        ]

    def get_required_components(self):
        """Потребность в полуфабрикатах по техкарте на объём quantity."""
        if not self.tech_card_id:
            return []
        return [
            (item.product, item.quantity * self.quantity)
            for item in self.tech_card.items.select_related("product").filter(product__isnull=False)
        ]

    def reserve_materials(self) -> None:
        """Зарезервировать материалы по техкарте (полуфабрикаты не резервируются)."""
        if self.status != self.STATUS_DRAFT:
            raise ValueError("Резерв возможен только для заказа в статусе «Черновик».")
        from django.db import transaction

        demand = {
            mid: q_per_unit * self.quantity
            for mid, q_per_unit in self.tech_card.material_quantities_per_unit_by_material_id().items()
            if q_per_unit * self.quantity > 0
        }
        if not demand:
            self.reservations.all().delete()
            self.status = self.STATUS_RESERVED
            self.save(update_fields=["status"])
            return

        with transaction.atomic():
            for mid, required in demand.items():
                stock_row = MaterialStock.objects.filter(
                    warehouse=self.material_warehouse,
                    material_id=mid,
                ).first()
                stock_qty = stock_row.quantity if stock_row else Decimal("0")
                reserved_po = (
                    MaterialReservation.objects.filter(
                        warehouse=self.material_warehouse,
                        material_id=mid,
                    )
                    .exclude(production_order_id=self.pk)
                    .aggregate(s=Sum("quantity"))["s"]
                    or Decimal("0")
                )
                reserved_assignment = (
                    AssignmentMaterialReservation.objects.filter(
                        warehouse=self.material_warehouse,
                        material_id=mid,
                    ).aggregate(s=Sum("quantity"))["s"]
                    or Decimal("0")
                )
                available = stock_qty - Decimal(reserved_po) - Decimal(reserved_assignment)
                if required > available:
                    material_name = (
                        Material.objects.filter(pk=mid).values_list("name", flat=True).first()
                        or f"ID={mid}"
                    )
                    raise ValueError(
                        f"Недостаточно доступного остатка материала «{material_name}» для резерва: "
                        f"нужно {required}, доступно {available} "
                        f"(остаток {stock_qty}, зарезервировано {Decimal(reserved_po) + Decimal(reserved_assignment)})."
                    )

            self.reservations.all().delete()
            for mid, required in demand.items():
                MaterialReservation.objects.create(
                    production_order=self,
                    warehouse=self.material_warehouse,
                    material_id=mid,
                    quantity=required,
                )
        self.status = self.STATUS_RESERVED
        self.save(update_fields=["status"])

    def release_reservation(self) -> None:
        """Снять резерв материалов."""
        if self.status not in (self.STATUS_RESERVED, self.STATUS_IN_PROGRESS):
            return
        self.reservations.all().delete()
        if self.status == self.STATUS_RESERVED:
            self.status = self.STATUS_DRAFT
            self.save(update_fields=["status"])


class MaterialReservation(models.Model):
    """Резерв материала по заказу на производство (не списывает склад, учитывается как занятый объём)."""
    production_order = models.ForeignKey(
        ProductionOrder,
        verbose_name="Заказ на производство",
        on_delete=models.CASCADE,
        related_name="reservations",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        verbose_name="Склад",
        on_delete=models.PROTECT,
    )
    material = models.ForeignKey(
        Material,
        verbose_name="Материал",
        on_delete=models.PROTECT,
    )
    quantity = models.DecimalField("Количество", max_digits=12, decimal_places=4)

    class Meta:
        verbose_name = "Резерв материала"
        verbose_name_plural = "Резервы материалов"
        unique_together = ("production_order", "material")

    def __str__(self) -> str:
        return f"{self.production_order}: {self.material} × {self.quantity}"


# --- Расширенный способ: этапы производства, техпроцесс, производственное задание ---


class ProductionStage(models.Model):
    """
    Этап производства — завершённый отрезок процесса (например: распил, печать принтов).
    Для этапа задаются склад материалов, стоимость нормо-часа, исполнители (сотрудники или контрагенты), мастер.
    Одни и те же этапы могут входить в разные техпроцессы.
    """
    name = models.CharField("Название", max_length=255)
    sequence = models.PositiveSmallIntegerField("Порядок", default=1)
    description = models.TextField("Описание", blank=True)
    material_warehouse = models.ForeignKey(
        Warehouse,
        verbose_name="Склад материалов",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="production_stages",
        help_text="Склад, откуда брать материалы для выполнения этапа",
    )
    hourly_rate = models.DecimalField(
        "Стоимость нормо-часа",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
        help_text="₽ за час работы этапа (станок или участок). Для лазера можно дополнительно задать стоимость метра реза ниже.",
    )
    cut_rate_per_meter = models.DecimalField(
        "Стоимость метра реза, ₽",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Для этапов вроде лазерной резки: затраты на 1 погонный метр реза. "
        "В техкарте на строке с этим этапом укажите норму длины реза на 1 изделие (м). "
        "Себестоимость строки: метры × эта ставка. Пусто — считать только по нормо-часу (если используете).",
    )
    track_real_time = models.BooleanField(
        "Факт. время",
        default=False,
        help_text="Фиксировать фактическое время начала и окончания работы по этапу",
    )
    any_employee_can_execute = models.BooleanField(
        "Любой сотрудник может выполнять этап",
        default=True,
        help_text="Если выключено, в производственном задании для этого этапа можно назначить только указанных исполнителей",
    )
    master = models.ForeignKey(
        Employee,
        verbose_name="Мастер этапа",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stages_as_master",
        help_text="Мастер может распределять задания между исполнителями",
    )
    executors = models.ManyToManyField(
        Employee,
        verbose_name="Исполнители (сотрудники)",
        related_name="stages_as_executor",
        blank=True,
        help_text="Сотрудники, которые могут выполнять этот этап. Если «Любой сотрудник» выключен — только они видят задания по этапу.",
    )
    counterparty_executors = models.ManyToManyField(
        Organization,
        verbose_name="Исполнители (контрагенты)",
        related_name="stages_as_executor",
        blank=True,
        help_text="Контрагенты (подрядчики), которые могут выполнять этап или услугу",
    )

    class Meta:
        verbose_name = "Этап производства"
        verbose_name_plural = "Этапы производства"
        ordering = ["sequence", "name"]

    def __str__(self) -> str:
        return self.name

    def employee_hourly_rate_for_plan(self) -> Decimal:
        """Ставка сотрудника для плановой оплаты: мастер этапа или первый исполнитель."""
        employee = self.master
        if not employee:
            employee = self.executors.order_by("full_name", "pk").first()
        if not employee:
            return Decimal("0")
        return Decimal(str(employee.hourly_rate or 0))


class ProductionStageCounterpartyService(models.Model):
    """Услуга, которую контрагент оказывает на данном этапе производства."""
    production_stage = models.ForeignKey(
        ProductionStage,
        on_delete=models.CASCADE,
        related_name="counterparty_services",
        verbose_name="Этап производства",
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="stage_services",
        verbose_name="Контрагент",
    )
    service = models.ForeignKey(
        "Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"product_kind": Product.PRODUCT_KIND_SERVICE},
        related_name="stage_counterparty_services",
        verbose_name="Услуга",
    )

    class Meta:
        verbose_name = "Услуга контрагента на этапе"
        verbose_name_plural = "Услуги контрагентов на этапе"
        unique_together = ("production_stage", "organization")

    def __str__(self) -> str:
        return f"{self.production_stage}: {self.organization} — {self.service or '—'}"


class TechProcess(models.Model):
    """Техпроцесс — упорядоченный набор этапов производства."""
    name = models.CharField("Название", max_length=255)
    description = models.TextField("Описание", blank=True)
    stages = models.ManyToManyField(
        ProductionStage,
        through="TechProcessStage",
        through_fields=("tech_process", "production_stage"),
        related_name="tech_processes",
        blank=True,
        verbose_name="Этапы",
    )

    class Meta:
        verbose_name = "Техпроцесс"
        verbose_name_plural = "Техпроцессы"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def get_stages_ordered(self):
        """Этапы в порядке следования в техпроцессе."""
        return self.stages.through.objects.filter(tech_process=self).order_by("order").select_related("production_stage")


class TechProcessStage(models.Model):
    """Порядок этапа в техпроцессе."""
    tech_process = models.ForeignKey(
        TechProcess,
        verbose_name="Техпроцесс",
        on_delete=models.CASCADE,
    )
    production_stage = models.ForeignKey(
        ProductionStage,
        verbose_name="Этап производства",
        on_delete=models.CASCADE,
    )
    order = models.PositiveSmallIntegerField("Порядок", default=1)

    class Meta:
        verbose_name = "Этап техпроцесса"
        verbose_name_plural = "Этапы техпроцесса"
        ordering = ["tech_process", "order"]
        unique_together = ("tech_process", "production_stage")

    def __str__(self) -> str:
        return f"{self.tech_process}: {self.production_stage}"


class ProductionAssignment(models.Model):
    """
    Производственное задание: какую продукцию и в каком объёме произвести по техкартам;
    материалы и затраты; ход выполнения. Может описывать смену, неделю или заказ покупателя;
    по этапам фиксируется выполнение. В системе — техпроцесс, позиции (техкарты, этапы),
    склады, статусы, снабжение полуфабрикатами, отклонения.
    """
    STATUS_DRAFT = "draft"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_IN_PROGRESS, "В работе"),
        (STATUS_COMPLETED, "Выполнено"),
        (STATUS_CANCELLED, "Отменено"),
    ]

    tech_process = models.ForeignKey(
        TechProcess,
        verbose_name="Техпроцесс",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignments",
    )
    order = models.ForeignKey(
        "Order",
        verbose_name="Заказ покупателя",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="production_assignments",
    )
    order_item = models.ForeignKey(
        "OrderItem",
        verbose_name="Позиция заказа покупателя",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="production_assignments",
    )
    product_warehouse = models.ForeignKey(
        Warehouse,
        verbose_name="Склад для продукции",
        on_delete=models.PROTECT,
        related_name="production_assignments_product",
    )
    material_warehouse = models.ForeignKey(
        Warehouse,
        verbose_name="Склад материалов",
        on_delete=models.PROTECT,
        related_name="production_assignments_material",
    )
    status = models.CharField(
        "Статус",
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )
    name = models.CharField(
        "Название задания",
        max_length=255,
        blank=True,
        help_text="Краткое название документа, например: Пошив платья",
    )
    date_planned = models.DateField("Плановая дата", null=True, blank=True)
    date_started = models.DateTimeField("Дата начала", null=True, blank=True)
    date_completed = models.DateTimeField("Дата завершения", null=True, blank=True)
    comment = models.TextField("Комментарий", blank=True)
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)
    # Снабжение: задание на полуфабрикаты, выполняемое перед основным
    supply_assignment = models.OneToOneField(
        "self",
        verbose_name="Задание снабжения (полуфабрикаты)",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supplies_main_assignment",
    )
    reserve_materials = models.BooleanField(
        "Резерв материалов",
        default=False,
        help_text="Зарезервировать материалы по потребности задания на выбранном складе материалов. "
        "При нескольких одновременных заданиях резерв помогает планировать снабжение.",
    )
    expectation = models.BooleanField(
        "Ожидание",
        default=False,
        help_text="Если включено, выпуск по заданию ещё не готов: такую продукцию можно учитывать в отчётах "
        "«Остатки» и «Управление закупками» (плановые количества к производству). Помогает планировать продажи. "
        "Когда продукция произведена — снимите флажок.",
    )

    class Meta:
        verbose_name = "Производственное задание"
        verbose_name_plural = "Производственные задания"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        if self.name and str(self.name).strip():
            return str(self.name).strip()
        if getattr(self, "pk", None):
            return f"Производственное задание #{self.pk}"
        return "Производственное задание"

    @classmethod
    def create_from_order_item(
        cls,
        order_item: "OrderItem",
        *,
        product_warehouse: "Warehouse" = None,
        material_warehouse: "Warehouse" = None,
    ):
        """
        Создать производственное задание из позиции заказа покупателя.
        Если уже есть активное задание по этой позиции — вернуть его.
        """
        if not order_item or not getattr(order_item, "pk", None):
            raise ValueError("Позиция заказа не найдена.")
        if not order_item.product_id:
            raise ValueError("В позиции заказа не указано изделие.")

        existing = cls.objects.filter(
            order_item_id=order_item.pk,
            status__in=(cls.STATUS_DRAFT, cls.STATUS_IN_PROGRESS),
        ).order_by("-id").first()
        if existing:
            return existing, False

        tech_card = TechCard.objects.filter(product_id=order_item.product_id).order_by("id").first()
        if not tech_card:
            raise ValueError(
                f"Для изделия «{order_item.product}» не найдена техкарта. "
                "Создайте техкарту и повторите создание задания."
            )

        product_warehouse = product_warehouse or Warehouse.objects.order_by("id").first()
        material_warehouse = material_warehouse or product_warehouse
        if not product_warehouse or not material_warehouse:
            raise ValueError("Не найден склад для создания производственного задания.")

        assignment = cls.objects.create(
            name=f"Заказ #{order_item.order_id} — {order_item.product}",
            tech_process=tech_card.tech_process,
            order_id=order_item.order_id,
            order_item_id=order_item.pk,
            product_warehouse=product_warehouse,
            material_warehouse=material_warehouse,
            status=cls.STATUS_DRAFT,
            date_planned=timezone.localdate(),
            comment="Создано автоматически из заказа покупателя.",
        )
        ProductionAssignmentItem.objects.create(
            assignment=assignment,
            tech_card=tech_card,
            quantity_planned=Decimal(str(order_item.quantity or 0)),
            quantity_produced=Decimal("0"),
            sequence=1,
        )
        return assignment, True

    def get_document_code_display(self) -> str:
        """Код документа для шапки формы (например 00017-1)."""
        if not getattr(self, "pk", None):
            return ""
        return f"{int(self.pk):05d}-1"

    def get_materials_by_stage_for_ui(self):
        """
        Материалы по этапам для вкладки «По материалам»: план из техкарт позиций,
        оценка себестоимости по средней цене материала.
        """
        from collections import OrderedDict

        if not self.pk:
            return []
        merged_stages: OrderedDict[str, dict] = OrderedDict()
        qs = self.items.select_related("production_stage").prefetch_related(
            Prefetch(
                "tech_card__items",
                queryset=TechCardItem.objects.filter(material__isnull=False).select_related(
                    "material"
                ),
            )
        )
        for item in qs:
            stage = (
                item.production_stage.name
                if item.production_stage_id
                else "Без этапа"
            )
            if stage not in merged_stages:
                merged_stages[stage] = {}
            by_mat = merged_stages[stage]
            tc_rows = item.tech_card.items.all()
            if item.production_stage_id:
                tc_rows = tc_rows.filter(production_stage_id=item.production_stage_id)
            for tc in tc_rows:
                if not tc.material_id:
                    continue
                need = tc.quantity * item.quantity_planned
                mid = tc.material_id
                if mid not in by_mat:
                    unit = tc.material.average_price or Decimal("0")
                    by_mat[mid] = {
                        "material": tc.material,
                        "planned": Decimal("0"),
                        "used": Decimal("0"),
                        "unit_cost": unit,
                    }
                by_mat[mid]["planned"] += need
        out = []
        for stage_name, mats in merged_stages.items():
            rows = []
            for _mid, d in mats.items():
                planned = d["planned"]
                unit = d["unit_cost"]
                line = (
                    (planned * unit).quantize(Decimal("0.01"))
                    if unit
                    else Decimal("0.00")
                )
                rows.append(
                    {
                        "material": d["material"],
                        "planned": planned,
                        "used": d["used"],
                        "unit_cost": unit,
                        "line_cost": line,
                    }
                )
            out.append({"stage": stage_name, "rows": rows})
        return out

    def get_labor_cost_estimate(self) -> Decimal:
        total = Decimal("0")
        for log in self.labor_logs.select_related("employee", "operation_type"):
            rate = log.employee.hourly_rate or log.operation_type.hourly_rate
            if rate is None:
                rate = Decimal("0")
            total += (log.minutes_spent / Decimal("60")) * rate
        return total.quantize(Decimal("0.01"))

    def get_cut_cost_planned_estimate(self) -> Decimal:
        """План по резу (м × ₽/м) по позициям задания."""
        if not self.pk:
            return Decimal("0")
        total = Decimal("0")
        for item in self.items.select_related("tech_card", "production_stage"):
            total += item.planned_cut_cost_amount()
        return total.quantize(Decimal("0.01"))

    def get_costs_summary_for_ui(self) -> dict:
        """Сводка для вкладки «По расходам» (оценка)."""
        materials_total = Decimal("0")
        for row in self.get_materials_flat_tab_rows():
            materials_total += row["line_cost"]
        labor = self.get_labor_cost_estimate() if self.pk else Decimal("0")
        cut = self.get_cut_cost_planned_estimate() if self.pk else Decimal("0")
        total = (materials_total + labor + cut).quantize(Decimal("0.01"))
        return {
            "materials": materials_total.quantize(Decimal("0.01")),
            "labor": labor,
            "cut": cut,
            "total": total,
        }

    def get_products_summary(self):
        """
        Сводка по продукции задания: изделие, план, выпуск, брак, годная продукция, оценка затрат.
        Для просмотра во вкладке «Продукция».
        """
        from collections import defaultdict
        by_product = defaultdict(lambda: {
            "planned": Decimal("0"),
            "produced": Decimal("0"),
            "defect": Decimal("0"),
            "good": Decimal("0"),
        })
        for item in self.items.select_related("tech_card__product").prefetch_related("defects"):
            product = item.tech_card.product
            if not product:
                continue
            defect_qty = item.get_defect_quantity()
            good_qty = item.good_quantity
            by_product[product]["planned"] += item.quantity_planned
            by_product[product]["produced"] += item.quantity_produced
            by_product[product]["defect"] += defect_qty
            by_product[product]["good"] += good_qty
        result = []
        for product, data in by_product.items():
            cost_estimate = (product.planned_total_cost or Decimal("0")) * data["good"]
            result.append({
                "product": product,
                "planned": data["planned"],
                "produced": data["produced"],
                "defect": data["defect"],
                "good": data["good"],
                "cost_estimate": cost_estimate.quantize(Decimal("0.01")),
            })
        return result

    def get_pending_products_for_stock_reports(self) -> list:
        """
        При включённом «Ожидании»: сколько продукции ещё не выпущено (план − годная),
        для отчётов «Остатки» и планирования закупок/продаж.
        """
        if not self.expectation or not self.pk:
            return []
        out = []
        for row in self.get_products_summary():
            rem = row["planned"] - row["good"]
            if rem > Decimal("0"):
                out.append(
                    {
                        "product": row["product"],
                        "quantity_pending": rem.quantize(Decimal("0.0001")),
                    }
                )
        out.sort(key=lambda r: (r["product"].name or "").lower())
        return out

    def get_material_requirements(self):
        """Потребность в материалах по всему заданию (всем позициям)."""
        from collections import defaultdict
        req = defaultdict(Decimal)
        for item in self.items.select_related("tech_card").prefetch_related("tech_card__items"):
            qs = item.tech_card.items.select_related("material").filter(material__isnull=False)
            if item.production_stage_id:
                qs = qs.filter(production_stage_id=item.production_stage_id)
            for tc_item in qs:
                req[tc_item.material] += tc_item.quantity * item.quantity_planned
        return list(req.items())

    def get_component_requirements(self):
        """Потребность в полуфабрикатах по всему заданию."""
        from collections import defaultdict
        req = defaultdict(Decimal)
        for item in self.items.select_related("tech_card").prefetch_related("tech_card__items"):
            qs = item.tech_card.items.select_related("product").filter(product__isnull=False)
            if item.production_stage_id:
                qs = qs.filter(production_stage_id=item.production_stage_id)
            for tc_item in qs:
                req[tc_item.product] += tc_item.quantity * item.quantity_planned
        return list(req.items())

    def get_total_planned_time_minutes(self) -> Decimal:
        """Суммарное плановое время по заданию: нормо-часы с техкарты (в мин) или нормы изделия."""
        total = Decimal("0")
        for item in self.items.select_related("tech_card__product").prefetch_related(
            "tech_card__product__labor_norms"
        ):
            tc = item.tech_card
            if tc.pk and tc.labor_lines.exists():
                for line in tc.labor_lines.all():
                    nh = line.norm_hours if line.norm_hours is not None else Decimal("0")
                    total += nh * Decimal("60") * item.quantity_planned
                continue
            product = tc.product
            if not product:
                continue
            for labor in product.labor_norms.all():
                total += labor.minutes_per_unit * item.quantity_planned
        return total

    def get_total_logged_time_minutes(self) -> Decimal:
        """Суммарное фактическое время по заданию (из LaborTimeLog)."""
        agg = self.labor_logs.aggregate(s=Sum("minutes_spent"))
        return agg["s"] or Decimal("0")

    def create_supply_assignment(self) -> "ProductionAssignment":
        """
        Создать производственное задание снабжения на полуфабрикаты.
        По техкартам основного задания определяются полуфабрикаты (product в составе),
        для каждого находится техкарта выпуска и добавляется позиция в новое задание.
        Сначала выполняют этапы задания снабжения, затем — основного.
        """
        if self.supply_assignment_id:
            raise ValueError("Задание снабжения уже создано.")
        component_req = self.get_component_requirements()  # [(product, qty), ...]
        if not component_req:
            raise ValueError("В техкартах задания нет полуфабрикатов для снабжения.")
        supply = ProductionAssignment.objects.create(
            product_warehouse=self.product_warehouse,
            material_warehouse=self.material_warehouse,
            status=ProductionAssignment.STATUS_DRAFT,
            date_planned=self.date_planned,
            comment=f"Снабжение для задания #{self.pk}",
        )
        for product, qty in component_req:
            tc = TechCard.objects.filter(product=product).first()
            if not tc:
                raise ValueError(
                    f"Нет техкарты для полуфабриката «{product.name}». "
                    "Создайте техкарту изделия для полуфабриката."
                )
            ProductionAssignmentItem.objects.create(
                assignment=supply,
                tech_card=tc,
                quantity_planned=qty,
                quantity_produced=0,
                sequence=supply.items.count() + 1,
            )
        self.supply_assignment = supply
        self.save(update_fields=["supply_assignment"])
        return supply

    def get_flat_planned_material_quantities(self) -> dict:
        """Суммарная потребность по material_id для всех позиций задания."""
        from collections import defaultdict

        need: dict[int, Decimal] = defaultdict(Decimal)
        if not self.pk:
            return {}
        qs = self.items.prefetch_related(
            Prefetch(
                "tech_card__items",
                queryset=TechCardItem.objects.filter(material__isnull=False).select_related(
                    "material"
                ),
            )
        )
        for item in qs:
            tc_rows = item.tech_card.items.all()
            if item.production_stage_id:
                tc_rows = tc_rows.filter(production_stage_id=item.production_stage_id)
            for tc in tc_rows:
                need[tc.material_id] += tc.quantity * item.quantity_planned
        return dict(need)

    def _material_reserved_elsewhere(self, material_id) -> Decimal:
        """Резерв того же материала на том же складе по другим документам."""
        if not self.material_warehouse_id:
            return Decimal("0")
        wh_id = self.material_warehouse_id
        po = (
            MaterialReservation.objects.filter(
                warehouse_id=wh_id, material_id=material_id
            ).aggregate(s=Sum("quantity"))["s"]
            or Decimal("0")
        )
        aq = AssignmentMaterialReservation.objects.filter(
            warehouse_id=wh_id, material_id=material_id
        )
        if self.pk:
            aq = aq.exclude(assignment_id=self.pk)
        oa = aq.aggregate(s=Sum("quantity"))["s"] or Decimal("0")
        return Decimal(po) + Decimal(oa)

    def _material_reserved_here(self, material_id) -> Decimal:
        if not self.pk:
            return Decimal("0")
        agg = AssignmentMaterialReservation.objects.filter(
            assignment_id=self.pk, material_id=material_id
        ).aggregate(s=Sum("quantity"))
        return agg["s"] or Decimal("0")

    def _material_used_overuse(self, material_id) -> Decimal:
        """Факт перерасхода по материалу (отклонения)."""
        if not self.pk:
            return Decimal("0")
        agg = ProductionDeviation.objects.filter(
            assignment=self,
            material_id=material_id,
            deviation_type=ProductionDeviation.DEVIATION_OVERUSE,
        ).aggregate(s=Sum("quantity"))
        return agg["s"] or Decimal("0")

    def get_materials_flat_tab_rows(self) -> list:
        """
        Строки вкладки «Материалы»: план, остаток на складе задания (без вычитания),
        резервы, доступно, оценка; оплата труда — на вкладке «По расходам».
        """
        if not self.pk or not self.material_warehouse_id:
            return []
        wh_id = self.material_warehouse_id
        demand = self.get_flat_planned_material_quantities()
        if not demand:
            return []
        materials = Material.objects.in_bulk(demand.keys())
        rows = []
        for mid in sorted(demand.keys(), key=lambda i: (materials[i].name.lower() if i in materials else "")):
            mat = materials.get(mid)
            if not mat:
                continue
            planned = demand[mid]
            stock_row = MaterialStock.objects.filter(
                warehouse_id=wh_id, material_id=mid
            ).first()
            stock_qty = stock_row.quantity if stock_row else Decimal("0")
            res_else = self._material_reserved_elsewhere(mid)
            res_here = self._material_reserved_here(mid)
            used = self._material_used_overuse(mid)
            available = stock_qty - res_else - res_here
            deviation = planned - used
            unit = mat.average_price or Decimal("0")
            line_cost = (planned * unit).quantize(Decimal("0.01")) if unit else Decimal("0.00")
            order_qty = max(Decimal("0"), planned - available)
            rows.append(
                {
                    "material": mat,
                    "planned": planned,
                    "used": used,
                    "deviation": deviation,
                    "reserved": res_here,
                    "unit_cost": unit,
                    "line_cost": line_cost,
                    "available": available,
                    "stock": stock_qty,
                    "order_qty": order_qty,
                }
            )
        return rows

    def sync_assignment_material_reservations(self) -> None:
        """Синхронизировать резервы с флажком и потребностью по техкартам."""
        from django.db import transaction

        if (
            not self.reserve_materials
            or not self.pk
            or not self.material_warehouse_id
        ):
            AssignmentMaterialReservation.objects.filter(assignment=self).delete()
            return
        demand = {
            mid: qty
            for mid, qty in self.get_flat_planned_material_quantities().items()
            if qty > 0
        }
        with transaction.atomic():
            for mid, qty in demand.items():
                stock_row = MaterialStock.objects.filter(
                    warehouse_id=self.material_warehouse_id,
                    material_id=mid,
                ).first()
                stock_qty = stock_row.quantity if stock_row else Decimal("0")
                reserved_elsewhere = self._material_reserved_elsewhere(mid)
                available = stock_qty - reserved_elsewhere
                if qty > available:
                    material_name = (
                        Material.objects.filter(pk=mid).values_list("name", flat=True).first()
                        or f"ID={mid}"
                    )
                    raise ValueError(
                        f"Недостаточно доступного остатка материала «{material_name}» для резерва задания: "
                        f"нужно {qty}, доступно {available} "
                        f"(остаток {stock_qty}, зарезервировано в других документах {reserved_elsewhere})."
                    )

            AssignmentMaterialReservation.objects.filter(assignment=self).delete()
            for mid, qty in demand.items():
                AssignmentMaterialReservation.objects.create(
                    assignment=self,
                    warehouse_id=self.material_warehouse_id,
                    material_id=mid,
                    quantity=qty,
                )


class AssignmentMaterialReservation(models.Model):
    """Резерв материала по производственному заданию (склад не списывается)."""

    assignment = models.ForeignKey(
        "ProductionAssignment",
        verbose_name="Производственное задание",
        on_delete=models.CASCADE,
        related_name="material_reservations",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        verbose_name="Склад",
        on_delete=models.CASCADE,
    )
    material = models.ForeignKey(
        Material,
        verbose_name="Материал",
        on_delete=models.CASCADE,
    )
    quantity = models.DecimalField("Количество", max_digits=12, decimal_places=4)

    class Meta:
        verbose_name = "Резерв материала (задание)"
        verbose_name_plural = "Резервы материалов (задания)"
        unique_together = ("assignment", "material")

    def __str__(self) -> str:
        return f"{self.assignment_id}: {self.material} × {self.quantity}"


class ProductionAssignmentItem(models.Model):
    """Позиция производственного задания — одна техкарта с объёмом и этапом выполнения."""
    STATUS_PENDING = "pending"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Ожидает"),
        (STATUS_IN_PROGRESS, "В работе"),
        (STATUS_COMPLETED, "Выполнено"),
    ]

    assignment = models.ForeignKey(
        ProductionAssignment,
        verbose_name="Производственное задание",
        on_delete=models.CASCADE,
        related_name="items",
    )
    production_stage = models.ForeignKey(
        ProductionStage,
        verbose_name="Этап производства",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignment_items",
    )
    tech_card = models.ForeignKey(
        TechCard,
        verbose_name="Техкарта",
        on_delete=models.PROTECT,
        related_name="assignment_items",
    )
    quantity_planned = models.DecimalField(
        "Объём производства",
        max_digits=12,
        decimal_places=4,
        help_text="Сколько раз произвести продукцию по этой техкарте в рамках задания.",
    )
    quantity_produced = models.DecimalField(
        "Фактически выпущено",
        max_digits=12,
        decimal_places=4,
        default=0,
    )
    sequence = models.PositiveSmallIntegerField(
        "Порядок выполнения",
        default=1,
        help_text="Несколько техкарт выполняются по возрастанию этого номера (как в списке позиций). "
        "Изменение порядка здесь меняет порядок в веб-приложении (реестр этапов и т.п.).",
    )
    status = models.CharField(
        "Статус этапа",
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    started_at = models.DateTimeField("Начало этапа", null=True, blank=True)
    completed_at = models.DateTimeField("Окончание этапа", null=True, blank=True)

    class Meta:
        verbose_name = "Позиция производственного задания"
        verbose_name_plural = "Позиции производственного задания"
        ordering = ["assignment", "sequence", "pk"]

    def __str__(self) -> str:
        return f"{self.assignment}: {self.tech_card} × {self.quantity_planned}"

    def planned_cut_cost_amount(self) -> Decimal:
        """
        Плановая сумма «рез по метрам» для этой позиции задания:
        объём × сумма (м × ₽/м) по строкам техкарты с тем же этапом (или все такие строки, если этап в позиции не задан).
        """
        tc = self.tech_card
        stage_id = self.production_stage_id
        q = self.quantity_planned or Decimal("0")
        per_unit = Decimal("0")
        for line in tc.items.select_related("production_stage"):
            L = line.cut_length_meters_per_unit
            if L is None or L <= 0:
                continue
            if stage_id and line.production_stage_id != stage_id:
                continue
            st = line.production_stage
            if not st:
                continue
            r = st.cut_rate_per_meter
            if r is None or r <= 0:
                continue
            per_unit += Decimal(str(L)) * Decimal(str(r))
        return (per_unit * q).quantize(Decimal("0.01"))

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        errors = {}
        planned = self.quantity_planned
        produced = (
            self.quantity_produced
            if self.quantity_produced is not None
            else Decimal("0")
        )
        if planned is not None and planned < produced:
            errors["quantity_planned"] = (
                "Объём производства не может быть меньше уже выпущенного по этой позиции "
                f"({produced})."
            )
        if errors:
            raise ValidationError(errors)

    def get_defect_quantity(self) -> Decimal:
        """Суммарное количество брака по этой позиции этапа."""
        agg = self.defects.aggregate(s=Sum("quantity"))
        return agg["s"] or Decimal("0")

    @property
    def good_quantity(self) -> Decimal:
        """Количество годной продукции (выпущено минус брак)."""
        return max(Decimal("0"), self.quantity_produced - self.get_defect_quantity())

    def get_required_materials(self):
        """Потребность в материалах по этой позиции."""
        from collections import defaultdict

        agg = defaultdict(lambda: Decimal("0"))
        items_qs = self.tech_card.items.filter(material__isnull=False)
        if self.production_stage_id:
            items_qs = items_qs.filter(production_stage_id=self.production_stage_id)
        for item in items_qs:
            agg[item.material_id] += item.quantity
        if not agg:
            return []
        mats = Material.objects.in_bulk(agg.keys())
        return [
            (mats[mid], q_per_unit * self.quantity_planned)
            for mid, q_per_unit in sorted(agg.items(), key=lambda x: x[0])
            if mid in mats
        ]

    def get_required_components(self):
        """Потребность в полуфабрикатах по этой позиции."""
        items_qs = self.tech_card.items.select_related("product").filter(product__isnull=False)
        if self.production_stage_id:
            items_qs = items_qs.filter(production_stage_id=self.production_stage_id)
        return [
            (item.product, item.quantity * self.quantity_planned)
            for item in items_qs
        ]

    def conduct(self) -> None:
        """
        Оформить выпуск по этой позиции: списать материалы и полуфабрикаты, оприходовать продукцию.
        """
        from django.utils import timezone
        from core.services.production_conduct import consume_material, consume_product, produce_product
        if self.status == self.STATUS_COMPLETED:
            return
        qty = self.quantity_produced if self.quantity_produced > 0 else self.quantity_planned
        assignment = self.assignment
        from collections import defaultdict

        # Списание строго по строкам техкарты выбранного этапа.
        stage_items_qs = self.tech_card.items.select_related("product").all()
        if self.production_stage_id:
            stage_items_qs = stage_items_qs.filter(production_stage_id=self.production_stage_id)

        agg_mat = defaultdict(lambda: Decimal("0"))
        for item in stage_items_qs.filter(material__isnull=False):
            agg_mat[item.material_id] += item.quantity
        materials_bulk = Material.objects.in_bulk(agg_mat.keys())
        for mid, q_per_unit in agg_mat.items():
            need = q_per_unit * qty
            if need <= 0:
                continue
            mat = materials_bulk.get(mid)
            if not mat:
                continue
            consume_material(
                warehouse=assignment.material_warehouse,
                material_id=mid,
                quantity=need,
                material_name=mat.name,
            )
        for item in stage_items_qs.filter(product__isnull=False):
            need = item.quantity * qty
            consume_product(
                warehouse=assignment.product_warehouse,
                product_id=item.product_id,
                quantity=need,
                product_name=item.product.name,
            )
        if self.tech_card.product_id:
            produce_product(
                warehouse=assignment.product_warehouse,
                product_id=self.tech_card.product_id,
                quantity=qty,
            )
        self.status = self.STATUS_COMPLETED
        if not self.completed_at:
            self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at"])
        # Если все позиции выполнены — закрыть задание
        if not assignment.items.filter(status__in=(self.STATUS_PENDING, self.STATUS_IN_PROGRESS)).exists():
            assignment.status = ProductionAssignment.STATUS_COMPLETED
            if not assignment.date_completed:
                assignment.date_completed = timezone.now()
            assignment.save(update_fields=["status", "date_completed"])


class ProductionDefect(models.Model):
    """
    Документ брака при выполнении этапа производства.
    Объём брака не может превышать объём выпуска по этапу.
    При создании бракованная продукция списывается со склада;
    записывается отрицательное отклонение (увеличивает себестоимость годной продукции).
    """
    assignment_item = models.ForeignKey(
        ProductionAssignmentItem,
        verbose_name="Позиция этапа",
        on_delete=models.CASCADE,
        related_name="defects",
    )
    quantity = models.DecimalField(
        "Объём брака",
        max_digits=12,
        decimal_places=4,
        help_text="Не может превышать фактически выпущенное по этапу",
    )
    product = models.ForeignKey(
        Product,
        verbose_name="Изделие (брак)",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="По умолчанию — продукция техкарты этапа",
    )
    comment = models.TextField("Комментарий", blank=True)
    created_at = models.DateTimeField("Дата", auto_now_add=True)

    class Meta:
        verbose_name = "Документ брака"
        verbose_name_plural = "Документы брака"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        product_name = self.product.name if self.product_id else self.assignment_item.tech_card.product
        return f"Брак: {product_name} × {self.quantity} (этап #{self.assignment_item_id})"

    def clean(self):
        from django.core.exceptions import ValidationError
        if not self.assignment_item_id or self.quantity is None:
            return
        total_defect = (
            ProductionDefect.objects.filter(assignment_item=self.assignment_item)
            .exclude(pk=self.pk)
            .aggregate(s=Sum("quantity"))["s"]
            or Decimal("0")
        )
        if total_defect + self.quantity > self.assignment_item.quantity_produced:
            raise ValidationError(
                f"Объём брака не может превышать выпуск по этапу: "
                f"выпущено {self.assignment_item.quantity_produced}, уже учтён брак {total_defect}."
            )

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        self.clean()
        super().save(*args, **kwargs)
        if not is_new or self.quantity <= 0:
            return
        product = self.product or self.assignment_item.tech_card.product
        if not product:
            return
        assignment = self.assignment_item.assignment
        warehouse = assignment.product_warehouse
        stock, _ = ProductStock.objects.get_or_create(
            warehouse=warehouse,
            product=product,
            defaults={"quantity": 0},
        )
        if stock.quantity < self.quantity:
            raise ValueError(
                f"Недостаточно продукции «{product.name}» на складе для списания брака: "
                f"нужно {self.quantity}, есть {stock.quantity}"
            )
        stock.quantity -= self.quantity
        stock.save(update_fields=["quantity"])
        # Записать отрицательное отклонение (брак)
        ProductionDeviation.objects.create(
            production_defect=self,
            assignment=assignment,
            assignment_item=self.assignment_item,
            product=product,
            quantity=self.quantity,
            deviation_type=ProductionDeviation.DEVIATION_DEFECT,
            comment=self.comment or "Брак по документу",
        )

    def delete(self, *args, **kwargs):
        # Вернуть продукцию на склад при удалении документа брака
        if self.quantity > 0:
            product = self.product or self.assignment_item.tech_card.product
            if product:
                assignment = self.assignment_item.assignment
                stock, _ = ProductStock.objects.get_or_create(
                    warehouse=assignment.product_warehouse,
                    product=product,
                    defaults={"quantity": 0},
                )
                stock.quantity += self.quantity
                stock.save(update_fields=["quantity"])
        ProductionDeviation.objects.filter(production_defect=self).delete()
        super().delete(*args, **kwargs)


class ProductionDeviation(models.Model):
    """Отклонение в производстве: брак, перерасход, экономия."""
    DEVIATION_DEFECT = "defect"
    DEVIATION_OVERUSE = "overuse"
    DEVIATION_SAVING = "saving"

    DEVIATION_CHOICES = [
        (DEVIATION_DEFECT, "Брак"),
        (DEVIATION_OVERUSE, "Перерасход"),
        (DEVIATION_SAVING, "Экономия"),
    ]

    production_defect = models.OneToOneField(
        ProductionDefect,
        verbose_name="Документ брака",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="deviation",
    )
    assignment = models.ForeignKey(
        ProductionAssignment,
        verbose_name="Производственное задание",
        on_delete=models.CASCADE,
        related_name="deviations",
    )
    assignment_item = models.ForeignKey(
        ProductionAssignmentItem,
        verbose_name="Позиция задания",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="deviations",
    )
    material = models.ForeignKey(
        Material,
        verbose_name="Материал",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    product = models.ForeignKey(
        Product,
        verbose_name="Изделие",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    quantity = models.DecimalField("Количество", max_digits=12, decimal_places=4)
    deviation_type = models.CharField(
        "Тип отклонения",
        max_length=20,
        choices=DEVIATION_CHOICES,
    )
    comment = models.TextField("Комментарий", blank=True)
    created_at = models.DateTimeField("Дата", auto_now_add=True)

    class Meta:
        verbose_name = "Отклонение в производстве"
        verbose_name_plural = "Отклонения в производстве"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        part = self.assignment_item or self.assignment
        subj = self.material or self.product or "—"
        return f"{self.get_deviation_type_display()}: {subj} × {self.quantity} ({part})"


class ProductionBatch(models.Model):
    product = models.ForeignKey(
        Product,
        verbose_name="Изделие",
        on_delete=models.PROTECT,
        related_name="batches",
    )
    order_item = models.ForeignKey(
        OrderItem,
        verbose_name="Позиция заказа",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="batches",
    )
    quantity_planned = models.PositiveIntegerField("Плановое количество")
    quantity_produced = models.PositiveIntegerField("Фактическое количество", default=0)
    started_at = models.DateTimeField("Начало", null=True, blank=True)
    finished_at = models.DateTimeField("Окончание", null=True, blank=True)

    def __str__(self) -> str:
        return f"Партия {self.product} x {self.quantity_planned}"

    class Meta:
        verbose_name = "Производственная партия"
        verbose_name_plural = "Производственные партии"

    @property
    def actual_material_cost(self) -> Decimal:
        total = Decimal("0")
        for usage in self.material_usages.select_related("material"):
            avg_price = usage.material.average_price
            if avg_price is None:
                continue
            total += usage.quantity * avg_price
        return total.quantize(Decimal("0.01")) if total else Decimal("0.00")

    @property
    def actual_labor_cost(self) -> Decimal:
        total = Decimal("0")
        for log in self.labor_logs.select_related("employee", "operation_type"):
            rate = log.employee.hourly_rate or log.operation_type.hourly_rate
            total += (log.minutes_spent / Decimal("60")) * rate
        return total.quantize(Decimal("0.01")) if total else Decimal("0.00")

    @property
    def actual_total_cost(self) -> Decimal:
        return (self.actual_material_cost + self.actual_labor_cost).quantize(Decimal("0.01"))


class ProductionMaterialUsage(models.Model):
    batch = models.ForeignKey(
        ProductionBatch,
        verbose_name="Партия",
        on_delete=models.CASCADE,
        related_name="material_usages",
    )
    material = models.ForeignKey(Material, verbose_name="Материал", on_delete=models.PROTECT)
    quantity = models.DecimalField("Количество", max_digits=12, decimal_places=3)

    def __str__(self) -> str:
        return f"{self.batch} - {self.material} {self.quantity}"

    class Meta:
        verbose_name = "Расход материала"
        verbose_name_plural = "Расход материалов"


class LaborTimeLog(models.Model):
    """Учёт времени: по партии (базовый) или по производственному заданию/этапу (расширенный)."""
    batch = models.ForeignKey(
        ProductionBatch,
        verbose_name="Партия",
        on_delete=models.CASCADE,
        related_name="labor_logs",
        null=True,
        blank=True,
    )
    production_assignment = models.ForeignKey(
        "ProductionAssignment",
        verbose_name="Производственное задание",
        on_delete=models.CASCADE,
        related_name="labor_logs",
        null=True,
        blank=True,
    )
    production_assignment_item = models.ForeignKey(
        "ProductionAssignmentItem",
        verbose_name="Позиция задания (этап)",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="labor_logs",
    )
    employee = models.ForeignKey(Employee, verbose_name="Сотрудник", on_delete=models.PROTECT)
    operation_type = models.ForeignKey(
        OperationType,
        verbose_name="Операция",
        on_delete=models.PROTECT,
    )
    minutes_spent = models.DecimalField("Затраченное время (мин)", max_digits=8, decimal_places=2)
    date = models.DateTimeField("Дата", auto_now_add=True)
    comment = models.CharField("Комментарий", max_length=255, blank=True)

    class Meta:
        verbose_name = "Трудозатраты"
        verbose_name_plural = "Трудозатраты"
        ordering = ["-date"]

    def clean(self):
        from django.core.exceptions import ValidationError
        if not self.batch_id and not self.production_assignment_id:
            raise ValidationError("Укажите партию или производственное задание.")

    def save(self, *args, **kwargs):
        if not self.batch_id and not self.production_assignment_id:
            raise ValueError("Трудозатраты должны быть привязаны к партии или к производственному заданию.")
        super().save(*args, **kwargs)


