"""
Документы закупок (раздел «Закупки» в админке).
Приёмка: шапка документа и строки; сумма шапки может заполняться из строк.
Проведение приёмки (статус «Проведён»): поступления MaterialBatch + остатки MaterialStock на склад.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Sum
from django.utils import timezone

from core.models import (
    Contract,
    Material,
    MaterialBatch,
    MaterialStock,
    Organization,
    Product,
    ProductStock,
    Warehouse,
)


class SupplierPurchaseOrder(models.Model):
    """Заказ поставщику: строки с товаром или материалом; для аналитики «ожидание» учитываются активные статусы."""

    STATUS_DRAFT = "draft"
    STATUS_SENT = "sent"
    STATUS_CONFIRMED = "confirmed"
    STATUS_CLOSED = "closed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_SENT, "Отправлен поставщику"),
        (STATUS_CONFIRMED, "Подтверждён"),
        (STATUS_CLOSED, "Закрыт"),
        (STATUS_CANCELLED, "Отменён"),
    ]

    #: Статусы, при которых количество по строкам входит в «Ожидание» (ещё не закрыт/не отменён).
    INCOMING_STATUSES = (STATUS_SENT, STATUS_CONFIRMED)

    number = models.CharField("Номер", max_length=32, unique=True, blank=True)
    ordered_at = models.DateTimeField("Дата заказа", default=timezone.now)
    supplier = models.ForeignKey(
        Organization,
        verbose_name="Поставщик",
        on_delete=models.PROTECT,
        related_name="purchase_orders_as_supplier",
    )
    our_organization = models.ForeignKey(
        Organization,
        verbose_name="Наша организация",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_orders_as_buyer",
        help_text="От имени какой своей организации оформлен заказ",
    )
    status = models.CharField(
        "Статус",
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        help_text="В «Ожидание» по товару входят строки заказов в статусах «Отправлен» и «Подтверждён».",
    )
    comment = models.TextField("Комментарий", blank=True)

    class Meta:
        verbose_name = "Заказ поставщику"
        verbose_name_plural = "Заказы поставщикам"
        ordering = ["-ordered_at", "-pk"]

    def __str__(self) -> str:
        return self.number or f"Заказ поставщику #{self.pk}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            n = f"ЗП-{self.pk:06d}"
            type(self).objects.filter(pk=self.pk).update(number=n)
            self.number = n


class SupplierPurchaseOrderLine(models.Model):
    """Строка заказа поставщику: либо номенклатура (товар), либо материал."""

    purchase_order = models.ForeignKey(
        SupplierPurchaseOrder,
        verbose_name="Заказ поставщику",
        on_delete=models.CASCADE,
        related_name="lines",
    )
    product = models.ForeignKey(
        Product,
        verbose_name="Товар",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supplier_order_lines",
    )
    material = models.ForeignKey(
        Material,
        verbose_name="Материал",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supplier_order_lines",
    )
    quantity = models.DecimalField("Количество", max_digits=14, decimal_places=4)
    quantity_received = models.DecimalField(
        "Получено",
        max_digits=14,
        decimal_places=4,
        default=Decimal("0"),
        help_text="Накапливается при проведении приёмок, привязанных к этой строке заказа.",
    )
    unit_price = models.DecimalField(
        "Цена за ед.",
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Ожидаемая цена закупки (необязательно)",
    )

    class Meta:
        verbose_name = "Строка заказа поставщику"
        verbose_name_plural = "Строки заказа поставщику"
        ordering = ["pk"]

    def __str__(self) -> str:
        if self.product_id:
            return f"{self.purchase_order} — {self.product}"
        if self.material_id:
            return f"{self.purchase_order} — {self.material}"
        return str(self.purchase_order)

    def clean(self):
        super().clean()
        has_p = bool(self.product_id)
        has_m = bool(self.material_id)
        if has_p == has_m:
            raise ValidationError("Укажите либо товар, либо материал (ровно одно из полей).")


class SupplierInvoice(models.Model):
    """Счёт поставщика."""
    OCR_PENDING = "pending"
    OCR_REVIEW = "review"
    OCR_APPLIED = "applied"
    OCR_FAILED = "failed"
    OCR_CHOICES = [
        (OCR_PENDING, "Ожидает распознавания"),
        (OCR_REVIEW, "Требует подтверждения"),
        (OCR_APPLIED, "Подтверждено"),
        (OCR_FAILED, "Ошибка распознавания"),
    ]
    EXP_CAT_MATERIALS = "materials"
    EXP_CAT_LOGISTICS = "logistics"
    EXP_CAT_SERVICES = "services"
    EXP_CAT_RENT = "rent"
    EXP_CAT_UTILITIES = "utilities"
    EXP_CAT_MARKETING = "marketing"
    EXP_CAT_IT = "it"
    EXP_CAT_EQUIPMENT = "equipment"
    EXP_CAT_OTHER = "other"
    EXPENSE_CATEGORY_CHOICES = [
        (EXP_CAT_MATERIALS, "Материалы/сырье"),
        (EXP_CAT_LOGISTICS, "Логистика/доставка"),
        (EXP_CAT_SERVICES, "Услуги"),
        (EXP_CAT_RENT, "Аренда"),
        (EXP_CAT_UTILITIES, "Коммунальные услуги"),
        (EXP_CAT_MARKETING, "Маркетинг/реклама"),
        (EXP_CAT_IT, "IT/связь/ПО"),
        (EXP_CAT_EQUIPMENT, "Оборудование"),
        (EXP_CAT_OTHER, "Прочее"),
    ]
    EXP_SUBCAT_RENT_OPERATING = "rent_operating_services"
    EXPENSE_SUBCATEGORY_CHOICES = [
        (EXP_SUBCAT_RENT_OPERATING, "Эксплуатационные услуги"),
    ]
    STATUS_DRAFT = "draft"
    STATUS_APPROVED = "approved"
    STATUS_PAID = "paid"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_APPROVED, "Утверждён"),
        (STATUS_PAID, "Оплачен"),
        (STATUS_CANCELLED, "Отменён"),
    ]

    number = models.CharField("Номер", max_length=32, unique=True, blank=True)
    invoice_date = models.DateField("Дата счёта", default=timezone.now)
    supplier = models.ForeignKey(
        Organization,
        verbose_name="Поставщик",
        on_delete=models.PROTECT,
        related_name="supplier_invoices",
    )
    our_organization = models.ForeignKey(
        Organization,
        verbose_name="Наша организация",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supplier_invoices_as_buyer",
    )
    total_amount = models.DecimalField(
        "Сумма", max_digits=14, decimal_places=2, default=Decimal("0"), blank=True
    )
    invoice_file = models.FileField(
        "Файл счёта (фото/PDF)",
        upload_to="supplier_invoices/raw/",
        blank=True,
    )
    ocr_status = models.CharField("Статус OCR", max_length=20, choices=OCR_CHOICES, default=OCR_PENDING)
    ocr_result_text = models.TextField("Результат OCR", blank=True)
    ocr_data = models.JSONField("Распознанные поля", default=dict, blank=True)
    ocr_reviewed_at = models.DateTimeField("Подтверждено OCR", null=True, blank=True)
    expense_category = models.CharField(
        "Категория расходов",
        max_length=32,
        choices=EXPENSE_CATEGORY_CHOICES,
        blank=True,
        default="",
    )
    expense_subcategory = models.CharField(
        "Подкатегория расходов",
        max_length=64,
        choices=EXPENSE_SUBCATEGORY_CHOICES,
        blank=True,
        default="",
    )
    status = models.CharField(
        "Статус",
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        blank=True,
    )
    comment = models.TextField("Назначение платежа", blank=True)

    class Meta:
        verbose_name = "Счёт поставщика"
        verbose_name_plural = "Счета поставщиков"
        ordering = ["-invoice_date", "-pk"]

    def __str__(self) -> str:
        return self.number or f"Счёт поставщика #{self.pk}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            n = f"СП-{self.pk:06d}"
            type(self).objects.filter(pk=self.pk).update(number=n)
            self.number = n


class SupplierInvoiceCategoryMemory(models.Model):
    """Память по категориям расходов для одинаковых формулировок назначения платежа."""

    normalized_name = models.CharField("Нормализованное наименование", max_length=255, unique=True)
    source_name = models.CharField("Наименование (как в счёте)", max_length=255)
    category = models.CharField(
        "Категория расходов",
        max_length=32,
        choices=SupplierInvoice.EXPENSE_CATEGORY_CHOICES,
    )
    confirmations = models.PositiveIntegerField("Подтверждений", default=1)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Память категории по счёту"
        verbose_name_plural = "Память категорий по счетам"
        ordering = ["-updated_at", "-pk"]

    def __str__(self) -> str:
        return f"{self.source_name} -> {self.get_category_display()} ({self.confirmations})"

    @property
    def is_auto_ready(self) -> bool:
        return self.confirmations >= 3


class GoodsReceipt(models.Model):
    """Приёмка на склад: материалы и/или готовая продукция (шапка документа)."""

    STATUS_DRAFT = "draft"
    STATUS_POSTED = "posted"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_POSTED, "Проведён"),
        (STATUS_CANCELLED, "Отменён"),
    ]

    number = models.CharField("Номер приёмки", max_length=32, unique=True, blank=True)
    received_at = models.DateTimeField("Дата и время приёмки", default=timezone.now)
    warehouse = models.ForeignKey(
        Warehouse,
        verbose_name="Склад",
        on_delete=models.PROTECT,
        related_name="goods_receipts",
    )
    supplier = models.ForeignKey(
        Organization,
        verbose_name="Контрагент",
        on_delete=models.PROTECT,
        related_name="goods_receipts_as_supplier",
        help_text="У кого заказывали",
    )
    our_organization = models.ForeignKey(
        Organization,
        verbose_name="Организация",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="goods_receipts_as_buyer",
        help_text="От какой своей организации оформлена приёмка",
    )
    total_amount = models.DecimalField(
        "Сумма (общая)",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Можно пересчитать из строк при сохранении",
    )
    paid_amount = models.DecimalField(
        "Оплачено", max_digits=14, decimal_places=2, default=Decimal("0"), blank=True
    )
    incoming_document_date = models.DateField(
        "Входящая дата", null=True, blank=True, help_text="Дата входящего документа поставщика"
    )
    incoming_number = models.CharField("Входящий номер", max_length=100, blank=True)
    contract = models.CharField("Договор", max_length=255, blank=True)
    contract_ref = models.ForeignKey(
        Contract,
        verbose_name="Договор (карточка)",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="goods_receipts",
        help_text="Действующий договор с контрагентом. Для проведения приёмки обязателен.",
    )
    project = models.CharField("Проект", max_length=255, blank=True)
    status = models.CharField(
        "Статус",
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        help_text="«Проведён» — приход на склад: материалы (движение + остаток материалов) или готовая продукция "
        "(остаток продукции). При указании строки заказа поставщику увеличивается «Получено» по заказу. "
        "Отменить проведение нельзя.",
    )
    is_sent = models.BooleanField("Отправлено", default=False)
    is_printed = models.BooleanField("Напечатано", default=False)
    comment = models.TextField("Комментарий", blank=True)
    posted_at = models.DateTimeField("Проведена", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "Приёмка"
        verbose_name_plural = "Приёмка"
        ordering = ["-received_at", "-pk"]

    def __str__(self) -> str:
        return self.number or f"Приёмка #{self.pk}"

    def clean(self):
        super().clean()
        if self.contract_ref_id:
            if self.supplier_id and self.contract_ref.counterparty_id != self.supplier_id:
                raise ValidationError({"contract_ref": "Выбранный договор относится к другому контрагенту."})
            if self.our_organization_id and self.contract_ref.our_organization_id != self.our_organization_id:
                raise ValidationError({"contract_ref": "Выбранный договор относится к другой нашей организации."})
        if not self.pk:
            return
        prev = GoodsReceipt.objects.filter(pk=self.pk).only("posted_at", "status").first()
        if prev and prev.posted_at and self.status != self.STATUS_POSTED:
            raise ValidationError(
                {"status": "Проведённую приёмку нельзя перевести в черновик или отменить."}
            )

    def _validate_contract_for_posting(self):
        if not self.contract_ref_id:
            raise ValidationError({"contract_ref": "Для проведения приёмки выберите договор."})
        c = self.contract_ref
        if c.status != Contract.STATUS_ACTIVE:
            raise ValidationError({"contract_ref": "Для проведения приёмки договор должен быть в статусе «Действует»."})
        doc_date = timezone.localdate(self.received_at) if self.received_at else timezone.localdate()
        if c.valid_until and doc_date > c.valid_until:
            raise ValidationError({"contract_ref": "Срок действия договора истек. Проведение запрещено."})

    def recalc_total_from_lines(self) -> None:
        agg = self.lines.aggregate(s=Sum("amount"))
        s = agg.get("s")
        self.total_amount = (s if s is not None else Decimal("0")).quantize(Decimal("0.01"))

    @transaction.atomic
    def conduct(self) -> None:
        """
        Проведение: строка с материалом — MaterialBatch (IN) + MaterialStock + current_stock материала;
        строка с товаром — приход на ProductStock (без движения MaterialBatch).
        Опционально привязка к строке заказа поставщику — увеличение quantity_received (не больше заказа).
        """
        locked = GoodsReceipt.objects.select_for_update().get(pk=self.pk)
        if locked.posted_at:
            return
        if locked.status != GoodsReceipt.STATUS_POSTED:
            return
        locked._validate_contract_for_posting()
        lines = list(
            GoodsReceiptLine.objects.filter(goods_receipt_id=self.pk).select_related(
                "material",
                "product",
                "supplier_order_line",
                "supplier_order_line__purchase_order",
            )
        )
        if not lines:
            raise ValidationError(
                "Чтобы провести приёмку, добавьте хотя бы одну строку с материалом или товаром."
            )
        ref = (locked.number or "").strip() or f"#{self.pk}"
        comment_base = (f"Приёмка {ref}")[:255]
        for line in lines:
            qty = (line.quantity or Decimal("0")).quantize(Decimal("0.001"))
            if qty <= 0:
                raise ValidationError("Укажите в каждой строке количество больше нуля.")
            up = (line.unit_price or Decimal("0")).quantize(Decimal("0.0001"))

            if line.supplier_order_line_id:
                pol = SupplierPurchaseOrderLine.objects.select_for_update().get(
                    pk=line.supplier_order_line_id
                )
                po = pol.purchase_order
                if po.supplier_id != locked.supplier_id:
                    raise ValidationError(
                        f"Строка заказа {pol} от другого поставщика, чем в шапке приёмки."
                    )
                if pol.material_id:
                    if not line.material_id or line.material_id != pol.material_id:
                        raise ValidationError(
                            "При привязке к строке заказа с материалом в строке приёмки должен быть тот же материал."
                        )
                elif pol.product_id:
                    if not line.product_id or line.product_id != pol.product_id:
                        raise ValidationError(
                            "При привязке к строке заказа с товаром в строке приёмки должен быть тот же товар."
                        )
                else:
                    raise ValidationError("Строка заказа поставщику без номенклатуры не может использоваться в приёмке.")
                rem = (pol.quantity - pol.quantity_received).quantize(Decimal("0.0001"))
                if qty > rem:
                    raise ValidationError(
                        f"По строке заказа «{pol}» можно принять не больше {rem} (остаток к поставке)."
                    )
                SupplierPurchaseOrderLine.objects.filter(pk=pol.pk).update(
                    quantity_received=F("quantity_received") + qty
                )

            if line.material_id:
                MaterialBatch.objects.create(
                    material=line.material,
                    movement_type=MaterialBatch.INCOMING,
                    quantity=qty,
                    unit_price=up,
                    comment=comment_base,
                )
                stock, _ = MaterialStock.objects.get_or_create(
                    warehouse=locked.warehouse,
                    material=line.material,
                    defaults={"quantity": Decimal("0")},
                )
                stock.quantity = (stock.quantity + qty).quantize(Decimal("0.001"))
                stock.save(update_fields=["quantity"])
                Material.objects.filter(pk=line.material_id).update(
                    current_stock=F("current_stock") + qty
                )
            elif line.product_id:
                pstock, _ = ProductStock.objects.get_or_create(
                    warehouse=locked.warehouse,
                    product=line.product,
                    defaults={"quantity": Decimal("0")},
                )
                pstock.quantity = (pstock.quantity + qty).quantize(Decimal("0.001"))
                pstock.save(update_fields=["quantity"])
            else:
                raise ValidationError("В строке приёмки должен быть указан материал или товар.")
        now = timezone.now()
        GoodsReceipt.objects.filter(pk=self.pk).update(posted_at=now)
        self.posted_at = now

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            n = f"ПРИ-{self.pk:06d}"
            type(self).objects.filter(pk=self.pk).update(number=n)
            self.number = n

    def delete(self, *args, **kwargs):
        if self.posted_at:
            raise ValidationError("Нельзя удалить проведённую приёмку.")
        super().delete(*args, **kwargs)


class GoodsReceiptLine(models.Model):
    """Строка приёмки: материал или готовый товар, опционально привязка к строке заказа поставщику."""

    goods_receipt = models.ForeignKey(
        GoodsReceipt,
        verbose_name="Приёмка",
        on_delete=models.CASCADE,
        related_name="lines",
    )
    material = models.ForeignKey(
        Material,
        verbose_name="Материал",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="goods_receipt_lines",
    )
    product = models.ForeignKey(
        Product,
        verbose_name="Товар (готовая продукция)",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="goods_receipt_lines",
    )
    supplier_order_line = models.ForeignKey(
        SupplierPurchaseOrderLine,
        verbose_name="Строка заказа поставщику",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="goods_receipt_lines",
        help_text="Если указано — при проведении увеличится «Получено» по заказу (поставщик и номенклатура должны совпадать).",
    )
    quantity = models.DecimalField("Количество", max_digits=14, decimal_places=4)
    unit_price = models.DecimalField("Цена за ед.", max_digits=14, decimal_places=4)
    amount = models.DecimalField("Сумма строки", max_digits=14, decimal_places=2)

    class Meta:
        verbose_name = "Строка приёмки"
        verbose_name_plural = "Строки приёмки"
        ordering = ["pk"]

    def __str__(self) -> str:
        if self.material_id:
            return f"{self.goods_receipt} — {self.material}"
        if self.product_id:
            return f"{self.goods_receipt} — {self.product}"
        return str(self.goods_receipt)

    def clean(self):
        super().clean()
        has_m = bool(self.material_id)
        has_p = bool(self.product_id)
        if has_m == has_p:
            raise ValidationError("Укажите либо материал, либо товар (ровно одно).")
        if self.supplier_order_line_id:
            pol = self.supplier_order_line
            if pol.material_id and (not self.material_id or self.material_id != pol.material_id):
                raise ValidationError(
                    {"supplier_order_line": "Материал в строке приёмки должен совпадать с материалом в строке заказа."}
                )
            if pol.product_id and (not self.product_id or self.product_id != pol.product_id):
                raise ValidationError(
                    {"supplier_order_line": "Товар в строке приёмки должен совпадать с товаром в строке заказа."}
                )

    def _sync_amount(self) -> None:
        q = self.quantity or Decimal("0")
        p = self.unit_price or Decimal("0")
        self.amount = (q * p).quantize(Decimal("0.01"))

    def full_clean(self, exclude=None, validate_unique=True, validate_constraints=True):
        self._sync_amount()
        super().full_clean(
            exclude=exclude,
            validate_unique=validate_unique,
            validate_constraints=validate_constraints,
        )

    def _ensure_receipt_mutable(self) -> None:
        if self.goods_receipt_id and GoodsReceipt.objects.filter(
            pk=self.goods_receipt_id, posted_at__isnull=False
        ).exists():
            raise ValidationError("Проведённую приёмку нельзя менять (в т.ч. строки состава).")

    def save(self, *args, **kwargs):
        self._ensure_receipt_mutable()
        self._sync_amount()
        super().save(*args, **kwargs)
        if self.goods_receipt_id:
            gr = GoodsReceipt.objects.get(pk=self.goods_receipt_id)
            gr.recalc_total_from_lines()
            GoodsReceipt.objects.filter(pk=gr.pk).update(total_amount=gr.total_amount)

    def delete(self, *args, **kwargs):
        self._ensure_receipt_mutable()
        rid = self.goods_receipt_id
        super().delete(*args, **kwargs)
        if rid:
            gr = GoodsReceipt.objects.filter(pk=rid).first()
            if gr:
                gr.recalc_total_from_lines()
                GoodsReceipt.objects.filter(pk=rid).update(total_amount=gr.total_amount)


class SupplierReturn(models.Model):
    """Возврат поставщику."""

    number = models.CharField("Номер", max_length=32, unique=True, blank=True)
    returned_at = models.DateTimeField("Дата возврата", default=timezone.now)
    supplier = models.ForeignKey(
        Organization,
        verbose_name="Поставщик",
        on_delete=models.PROTECT,
        related_name="supplier_returns",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        verbose_name="Склад",
        on_delete=models.PROTECT,
        related_name="supplier_returns",
    )
    total_amount = models.DecimalField(
        "Сумма", max_digits=14, decimal_places=2, default=Decimal("0"), blank=True
    )
    status = models.CharField("Статус", max_length=20, default="draft", blank=True)
    comment = models.TextField("Комментарий", blank=True)

    class Meta:
        verbose_name = "Возврат поставщику"
        verbose_name_plural = "Возвраты поставщикам"
        ordering = ["-returned_at", "-pk"]

    def __str__(self) -> str:
        return self.number or f"Возврат #{self.pk}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            n = f"ВП-{self.pk:06d}"
            type(self).objects.filter(pk=self.pk).update(number=n)
            self.number = n


class ReceivedVatInvoice(models.Model):
    """Полученный счёт-фактура (учётный документ)."""

    number = models.CharField("Номер", max_length=32, unique=True, blank=True)
    invoice_date = models.DateField("Дата", default=timezone.now)
    supplier = models.ForeignKey(
        Organization,
        verbose_name="Поставщик",
        on_delete=models.PROTECT,
        related_name="received_vat_invoices",
    )
    our_organization = models.ForeignKey(
        Organization,
        verbose_name="Наша организация",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="received_vat_invoices_as_buyer",
    )
    total_amount = models.DecimalField(
        "Сумма", max_digits=14, decimal_places=2, default=Decimal("0"), blank=True
    )
    status = models.CharField("Статус", max_length=20, default="draft", blank=True)
    comment = models.TextField("Комментарий", blank=True)

    class Meta:
        verbose_name = "Счёт-фактура полученный"
        verbose_name_plural = "Счета-фактуры полученные"
        ordering = ["-invoice_date", "-pk"]

    def __str__(self) -> str:
        return self.number or f"СФ #{self.pk}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            n = f"СФ-{self.pk:06d}"
            type(self).objects.filter(pk=self.pk).update(number=n)
            self.number = n


class PurchaseManagementProduct(Product):
    """Прокси для таблицы «Управление закупками» (аналитика по номенклатуре)."""

    class Meta:
        proxy = True
        verbose_name = "Позиция (управление закупками)"
        verbose_name_plural = "Управление закупками"
