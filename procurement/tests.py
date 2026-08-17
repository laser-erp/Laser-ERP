from datetime import date
from decimal import Decimal

from django.test import TestCase

from core.models import (
    Contract,
    Material,
    MaterialBatch,
    MaterialStock,
    Organization,
    Warehouse,
)
from procurement.admin import GoodsReceiptLineForm
from procurement.models import GoodsReceipt, GoodsReceiptLine
from procurement.views import _qty_price_from_pack


class GoodsReceiptLinePackFormTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Поставщик стрейча", is_supplier=True)
        self.wh = Warehouse.objects.create(name="Склад упаковки", organization=self.org)
        self.material = Material.objects.create(name="Стрейч 500 мм", unit="м")
        self.receipt = GoodsReceipt.objects.create(warehouse=self.wh, supplier=self.org)

    def test_roll_pack_and_amount_fill_meters_and_unit_price(self):
        form = GoodsReceiptLineForm(
            data={
                "goods_receipt": str(self.receipt.pk),
                "material": str(self.material.pk),
                "pack_count": "1",
                "qty_in_pack": "300",
                "amount": "1500",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["quantity"], Decimal("300.0000"))
        self.assertEqual(form.cleaned_data["unit_price"], Decimal("5.0000"))

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["quantity"], Decimal("300.0000"))
        self.assertEqual(form.cleaned_data["unit_price"], Decimal("5.0000"))


class GoodsReceiptPackHelperTests(TestCase):
    def test_one_roll_amount_to_meters(self):
        qty, price = _qty_price_from_pack(None, None, None, Decimal("300"), Decimal("1500"))
        self.assertEqual(qty, Decimal("300.0000"))
        self.assertEqual(price, Decimal("5.0000"))

    def test_two_rolls(self):
        qty, price = _qty_price_from_pack(None, None, Decimal("2"), Decimal("300"), Decimal("3000"))
        self.assertEqual(qty, Decimal("600.0000"))
        self.assertEqual(price, Decimal("5.0000"))


class GoodsReceiptDeleteReversesStockTests(TestCase):
    def test_deleting_posted_receipt_rolls_back_stock(self):
        supplier = Organization.objects.create(name="Поставщик", is_supplier=True)
        ours = Organization.objects.create(name="Мы", is_supplier=False, is_buyer=True)
        wh = Warehouse.objects.create(name="Склад", organization=ours)
        material = Material.objects.create(name="Тестовый лист", unit="шт", current_stock=Decimal("10"))
        contract = Contract.objects.create(
            number="Д-1",
            contract_date=date.today(),
            contract_type=Contract.TYPE_SUPPLIER,
            status=Contract.STATUS_ACTIVE,
            our_organization=ours,
            counterparty=supplier,
        )
        receipt = GoodsReceipt.objects.create(
            warehouse=wh,
            supplier=supplier,
            our_organization=ours,
            contract_ref=contract,
            status=GoodsReceipt.STATUS_POSTED,
        )
        GoodsReceiptLine.objects.create(
            goods_receipt=receipt,
            material=material,
            quantity=Decimal("2"),
            unit_price=Decimal("100"),
            amount=Decimal("200"),
        )
        receipt.conduct()
        material.refresh_from_db()
        self.assertEqual(material.current_stock, Decimal("12.000"))
        self.assertEqual(material.purchase_price, Decimal("100.0000"))
        self.assertTrue(MaterialBatch.objects.filter(material=material, comment__startswith="Приёмка").exists())
        self.assertEqual(MaterialStock.objects.get(warehouse=wh, material=material).quantity, Decimal("2.000"))

        receipt.delete()
        material.refresh_from_db()
        self.assertEqual(material.current_stock, Decimal("10.000"))
        self.assertFalse(GoodsReceipt.objects.filter(pk=receipt.pk).exists())
        self.assertFalse(MaterialBatch.objects.filter(material=material, comment__startswith="Приёмка").exists())
        self.assertEqual(MaterialStock.objects.get(warehouse=wh, material=material).quantity, Decimal("0.000"))


class SupplierInvoiceExpenseCategoryTests(TestCase):
    def test_szuk_operating_services_are_utilities_electricity(self):
        from procurement.models import SupplierInvoice
        from procurement.services.invoice_ocr import apply_ocr_data_to_supplier_invoice

        supplier = Organization.objects.create(name='ООО "СЗУК"', is_supplier=True)
        invoice = SupplierInvoice.objects.create(
            supplier=supplier,
            total_amount=Decimal("612.93"),
            ocr_data={
                "payment_purpose": "Начислено Эксплуатационные услуги по договору за Июнь 2026 г.",
                "total_amount": "612.93",
            },
        )
        apply_ocr_data_to_supplier_invoice(invoice)
        invoice.refresh_from_db()
        self.assertEqual(invoice.expense_category, SupplierInvoice.EXP_CAT_UTILITIES)
        self.assertEqual(invoice.expense_subcategory, SupplierInvoice.EXP_SUBCAT_RENT_OPERATING)

    def test_gsi_rent_stays_rent(self):
        from procurement.models import SupplierInvoice
        from procurement.services.invoice_ocr import apply_ocr_data_to_supplier_invoice

        supplier = Organization.objects.create(name='ООО "ГСИ"', is_supplier=True)
        invoice = SupplierInvoice.objects.create(
            supplier=supplier,
            total_amount=Decimal("14777.25"),
            ocr_data={
                "payment_purpose": "Авансовый платеж 1 часть арендной платы по договору за Май 2026 г.",
                "total_amount": "14777.25",
            },
        )
        apply_ocr_data_to_supplier_invoice(invoice)
        invoice.refresh_from_db()
        self.assertEqual(invoice.expense_category, SupplierInvoice.EXP_CAT_RENT)


class GoodsReceiptTotalTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Фанера-piter", is_supplier=True)
        self.wh = Warehouse.objects.create(name="Склад материалов", organization=self.org)
        self.receipt = GoodsReceipt.objects.create(warehouse=self.wh, supplier=self.org)
        self.mat = Material.objects.create(name="Фанера ФК 900*600 3мм", unit="лист")

    def test_total_is_sum_of_qty_times_price_not_unit_price(self):
        GoodsReceiptLine.objects.create(
            goods_receipt=self.receipt,
            material=self.mat,
            quantity=Decimal("3"),
            unit_price=Decimal("183.19"),
            amount=Decimal("183.19"),
        )
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.total_amount, Decimal("549.57"))

    def test_recalc_after_save_related_pattern(self):
        GoodsReceiptLine.objects.create(
            goods_receipt=self.receipt,
            material=self.mat,
            quantity=Decimal("3"),
            unit_price=Decimal("183.19"),
            amount=Decimal("549.57"),
        )
        mat2 = Material.objects.create(name="Фанера ФК 621*621 3мм", unit="лист")
        GoodsReceiptLine.objects.create(
            goods_receipt=self.receipt,
            material=mat2,
            quantity=Decimal("1"),
            unit_price=Decimal("128.77"),
            amount=Decimal("128.77"),
        )
        self.receipt.recalc_total_from_lines()
        self.assertEqual(self.receipt.total_amount, Decimal("678.34"))


class FaneraNestReceiptTests(TestCase):
    def test_four_sheets_3mm_matches_shop_total(self):
        from procurement.services.fanera_nest_receipt import calc_nest_receipt_lines

        lines, meta = calc_nest_receipt_lines(thickness_mm="3", source_sheets=4)
        self.assertEqual(meta["source_sheets"], 4)
        self.assertEqual(meta["shop_total"], "3060.00")
        self.assertEqual(meta["receipt_total"], "3060.00")
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0].quantity, Decimal("12"))
        self.assertEqual(lines[1].quantity, Decimal("4"))
        self.assertEqual(lines[2].quantity, Decimal("4"))

    def test_blanks_900x600_rounds_up_sheets(self):
        from procurement.services.fanera_nest_receipt import (
            calc_nest_receipt_lines,
            source_sheets_for_blanks,
        )

        self.assertEqual(source_sheets_for_blanks(10), 4)
        lines, meta = calc_nest_receipt_lines(thickness_mm="3", blanks_900x600=10)
        self.assertEqual(meta["source_sheets"], 4)
        self.assertEqual(meta["blanks_900x600"], 12)
        total = sum(line.amount for line in lines)
        self.assertEqual(total, Decimal("3060.00"))

    def test_build_payload_has_three_thicknesses(self):
        from procurement.services.fanera_nest_receipt import build_nest_kits_payload

        payload = build_nest_kits_payload()
        self.assertEqual(len(payload["kits"]), 3)
        kit3 = payload["kits"][0]
        self.assertEqual(kit3["thickness_mm"], "3")
        self.assertEqual(len(kit3["pieces"]), 3)

