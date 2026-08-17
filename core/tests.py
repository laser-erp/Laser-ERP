from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import (
    AssignmentMaterialReservation,
    Material,
    MaterialBatch,
    MaterialGroup,
    MaterialGroupBrand,
    MaterialGroupColor,
    MaterialGroupType,
    MaterialReservation,
    MaterialStock,
    Employee,
    Organization,
    Order,
    OrderItem,
    Product,
    ProductMaterial,
    ProductModification,
    ProductStock,
    ProductionAssignment,
    ProductionAssignmentItem,
    ProductionOrder,
    ProductionStage,
    TechCard,
    TechCardItem,
    TechCardLaborLine,
    TechProcessStage,
    TechOperation,
    TechOperationMaterial,
    TechOperationProduct,
    TechProcess,
    ProductDisassembly,
    Warehouse,
)


class ProductionAssignmentStageConductTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Test Org")
        self.product_wh = Warehouse.objects.create(name="WH Product", organization=self.org)
        self.material_wh = Warehouse.objects.create(name="WH Material", organization=self.org)
        self.stage_cut = ProductionStage.objects.create(name="Резка", sequence=1)
        self.stage_pack = ProductionStage.objects.create(name="Упаковка", sequence=2)
        self.tech_process = TechProcess.objects.create(name="Main Tech Process")
        self.finished_product = Product.objects.create(
            name="Готовое изделие",
            min_stock=Decimal("0"),
        )
        self.component_product = Product.objects.create(
            name="Полуфабрикат",
            min_stock=Decimal("0"),
        )
        self.component_product_stage2 = Product.objects.create(
            name="Полуфабрикат Этап 2",
            min_stock=Decimal("0"),
        )
        self.material = Material.objects.create(name="Лист", unit="шт")
        self.tech_card = TechCard.objects.create(
            name="TC-1",
            tech_process=self.tech_process,
            product=self.finished_product,
        )
        TechCardItem.objects.create(
            tech_card=self.tech_card,
            material=self.material,
            quantity=Decimal("2"),
            production_stage=self.stage_cut,
        )
        TechCardItem.objects.create(
            tech_card=self.tech_card,
            material=self.material,
            quantity=Decimal("5"),
            production_stage=self.stage_pack,
        )
        TechCardItem.objects.create(
            tech_card=self.tech_card,
            product=self.component_product,
            quantity=Decimal("1"),
            item_kind=TechCardItem.KIND_COMPONENT,
            production_stage=self.stage_cut,
        )
        TechCardItem.objects.create(
            tech_card=self.tech_card,
            product=self.component_product_stage2,
            quantity=Decimal("3"),
            item_kind=TechCardItem.KIND_COMPONENT,
            production_stage=self.stage_pack,
        )

    def test_required_materials_and_components_are_stage_scoped(self):
        assignment = ProductionAssignment.objects.create(
            product_warehouse=self.product_wh,
            material_warehouse=self.material_wh,
        )
        item = ProductionAssignmentItem.objects.create(
            assignment=assignment,
            tech_card=self.tech_card,
            production_stage=self.stage_cut,
            quantity_planned=Decimal("2"),
            quantity_produced=Decimal("0"),
            sequence=1,
        )

        materials = item.get_required_materials()
        components = item.get_required_components()

        self.assertEqual(len(materials), 1)
        self.assertEqual(materials[0][0].pk, self.material.pk)
        self.assertEqual(materials[0][1], Decimal("4"))
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0][0].pk, self.component_product.pk)
        self.assertEqual(components[0][1], Decimal("2"))

    def test_conduct_uses_only_selected_stage_rows(self):
        assignment = ProductionAssignment.objects.create(
            product_warehouse=self.product_wh,
            material_warehouse=self.material_wh,
        )
        item = ProductionAssignmentItem.objects.create(
            assignment=assignment,
            tech_card=self.tech_card,
            production_stage=self.stage_cut,
            quantity_planned=Decimal("2"),
            quantity_produced=Decimal("0"),
            sequence=1,
        )
        MaterialStock.objects.create(
            warehouse=self.material_wh,
            material=self.material,
            quantity=Decimal("4"),
        )
        ProductStock.objects.create(
            warehouse=self.product_wh,
            product=self.component_product,
            quantity=Decimal("2"),
        )

        item.conduct()

        material_stock = MaterialStock.objects.get(warehouse=self.material_wh, material=self.material)
        component_stock = ProductStock.objects.get(warehouse=self.product_wh, product=self.component_product)
        finished_stock = ProductStock.objects.get(warehouse=self.product_wh, product=self.finished_product)
        item.refresh_from_db()
        assignment.refresh_from_db()

        self.assertEqual(material_stock.quantity, Decimal("0"))
        self.assertEqual(component_stock.quantity, Decimal("0"))
        self.assertEqual(finished_stock.quantity, Decimal("2"))
        self.assertEqual(item.status, ProductionAssignmentItem.STATUS_COMPLETED)
        self.assertEqual(assignment.status, ProductionAssignment.STATUS_COMPLETED)


class ProductionAssignmentReservationsTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Test Org Rsv")
        self.product_wh = Warehouse.objects.create(name="WH Product Rsv", organization=self.org)
        self.material_wh = Warehouse.objects.create(name="WH Material Rsv", organization=self.org)
        self.stage_cut = ProductionStage.objects.create(name="Резка Rsv", sequence=1)
        self.stage_pack = ProductionStage.objects.create(name="Упаковка Rsv", sequence=2)
        self.tech_process = TechProcess.objects.create(name="Tech Process Rsv")
        self.finished_product = Product.objects.create(name="Изделие Rsv", min_stock=Decimal("0"))
        self.material = Material.objects.create(name="Материал Rsv", unit="шт")
        self.tech_card = TechCard.objects.create(
            name="TC-Rsv",
            tech_process=self.tech_process,
            product=self.finished_product,
        )
        TechCardItem.objects.create(
            tech_card=self.tech_card,
            material=self.material,
            quantity=Decimal("2"),
            production_stage=self.stage_cut,
        )
        TechCardItem.objects.create(
            tech_card=self.tech_card,
            material=self.material,
            quantity=Decimal("5"),
            production_stage=self.stage_pack,
        )

    def test_flat_planned_material_quantities_are_stage_scoped(self):
        assignment = ProductionAssignment.objects.create(
            product_warehouse=self.product_wh,
            material_warehouse=self.material_wh,
            reserve_materials=True,
        )
        ProductionAssignmentItem.objects.create(
            assignment=assignment,
            tech_card=self.tech_card,
            production_stage=self.stage_cut,
            quantity_planned=Decimal("3"),
            sequence=1,
        )
        ProductionAssignmentItem.objects.create(
            assignment=assignment,
            tech_card=self.tech_card,
            production_stage=self.stage_pack,
            quantity_planned=Decimal("2"),
            sequence=2,
        )

        need = assignment.get_flat_planned_material_quantities()
        self.assertIn(self.material.pk, need)
        # 3 * 2 (stage_cut) + 2 * 5 (stage_pack) = 16
        self.assertEqual(need[self.material.pk], Decimal("16"))

    def test_sync_assignment_material_reservations_uses_stage_scoped_need(self):
        assignment = ProductionAssignment.objects.create(
            product_warehouse=self.product_wh,
            material_warehouse=self.material_wh,
            reserve_materials=True,
        )
        ProductionAssignmentItem.objects.create(
            assignment=assignment,
            tech_card=self.tech_card,
            production_stage=self.stage_cut,
            quantity_planned=Decimal("4"),
            sequence=1,
        )
        MaterialStock.objects.create(
            warehouse=self.material_wh,
            material=self.material,
            quantity=Decimal("20"),
        )

        assignment.sync_assignment_material_reservations()

        rows = assignment.material_reservations.filter(material=self.material)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().quantity, Decimal("8"))

    def test_assignment_sync_reservations_raises_when_available_is_insufficient(self):
        assignment_main = ProductionAssignment.objects.create(
            product_warehouse=self.product_wh,
            material_warehouse=self.material_wh,
            reserve_materials=True,
        )
        ProductionAssignmentItem.objects.create(
            assignment=assignment_main,
            tech_card=self.tech_card,
            production_stage=self.stage_cut,
            quantity_planned=Decimal("4"),
            sequence=1,
        )
        # Требование = 4 * 2 = 8
        MaterialStock.objects.create(
            warehouse=self.material_wh,
            material=self.material,
            quantity=Decimal("10"),
        )
        assignment_other = ProductionAssignment.objects.create(
            product_warehouse=self.product_wh,
            material_warehouse=self.material_wh,
            reserve_materials=True,
        )
        AssignmentMaterialReservation.objects.create(
            assignment=assignment_other,
            warehouse=self.material_wh,
            material=self.material,
            quantity=Decimal("5"),
        )

        with self.assertRaises(ValueError):
            assignment_main.sync_assignment_material_reservations()

    def test_production_order_reserve_raises_when_available_is_insufficient(self):
        order = ProductionOrder.objects.create(
            tech_card=self.tech_card,
            quantity=Decimal("4"),
            product_warehouse=self.product_wh,
            material_warehouse=self.material_wh,
            status=ProductionOrder.STATUS_DRAFT,
        )
        # Требование = 4 * 2 = 8
        MaterialStock.objects.create(
            warehouse=self.material_wh,
            material=self.material,
            quantity=Decimal("10"),
        )
        other_order = ProductionOrder.objects.create(
            tech_card=self.tech_card,
            quantity=Decimal("1"),
            product_warehouse=self.product_wh,
            material_warehouse=self.material_wh,
            status=ProductionOrder.STATUS_DRAFT,
        )
        MaterialReservation.objects.create(
            production_order=other_order,
            warehouse=self.material_wh,
            material=self.material,
            quantity=Decimal("4"),
        )

        with self.assertRaises(ValueError):
            order.reserve_materials()


class TechOperationConductServiceTests(TestCase):
    def test_tech_operation_conduct_consumes_and_produces_via_unified_logic(self):
        org = Organization.objects.create(name="TechOp Org")
        product_wh = Warehouse.objects.create(name="TechOp Product WH", organization=org)
        material_wh = Warehouse.objects.create(name="TechOp Material WH", organization=org)
        tp = TechProcess.objects.create(name="TechOp TP")
        finished = Product.objects.create(name="TechOp Finished", min_stock=Decimal("0"))
        component = Product.objects.create(name="TechOp Component", min_stock=Decimal("0"))
        material = Material.objects.create(name="TechOp Material", unit="шт")
        tc = TechCard.objects.create(name="TechOp TC", tech_process=tp, product=finished)
        TechCardItem.objects.create(
            tech_card=tc,
            product=component,
            quantity=Decimal("1"),
            item_kind=TechCardItem.KIND_COMPONENT,
        )
        MaterialStock.objects.create(
            warehouse=material_wh,
            material=material,
            quantity=Decimal("3"),
        )
        ProductStock.objects.create(
            warehouse=product_wh,
            product=component,
            quantity=Decimal("2"),
        )
        op = TechOperation.objects.create(
            organization=org,
            product_warehouse=product_wh,
            material_warehouse=material_wh,
            tech_card=tc,
        )
        TechOperationMaterial.objects.create(
            tech_operation=op,
            material=material,
            quantity=Decimal("3"),
        )
        TechOperationProduct.objects.create(
            tech_operation=op,
            product=finished,
            quantity=Decimal("2"),
        )

        op.conduct()

        mat_qty = MaterialStock.objects.get(warehouse=material_wh, material=material).quantity
        comp_qty = ProductStock.objects.get(warehouse=product_wh, product=component).quantity
        finished_qty = ProductStock.objects.get(warehouse=product_wh, product=finished).quantity
        op.refresh_from_db()

        self.assertEqual(mat_qty, Decimal("0"))
        self.assertEqual(comp_qty, Decimal("0"))
        self.assertEqual(finished_qty, Decimal("2"))
        self.assertEqual(op.status, TechOperation.STATUS_COMPLETED)


class ProductDisassemblyConductServiceTests(TestCase):
    def test_product_disassembly_uses_unified_service(self):
        org = Organization.objects.create(name="Disassembly Org")
        product_wh = Warehouse.objects.create(name="Disassembly Product WH", organization=org)
        material_wh = Warehouse.objects.create(name="Disassembly Material WH", organization=org)
        tp = TechProcess.objects.create(name="Disassembly TP")
        finished = Product.objects.create(name="Disassembly Finished", min_stock=Decimal("0"))
        material = Material.objects.create(name="Disassembly Material", unit="шт")
        tc = TechCard.objects.create(name="Disassembly TC", tech_process=tp, product=finished)
        TechCardItem.objects.create(
            tech_card=tc,
            material=material,
            quantity=Decimal("2"),
        )
        ProductStock.objects.create(
            warehouse=product_wh,
            product=finished,
            quantity=Decimal("3"),
        )
        MaterialStock.objects.create(
            warehouse=material_wh,
            material=material,
            quantity=Decimal("1"),
        )
        disassembly = ProductDisassembly.objects.create(
            tech_card=tc,
            quantity=Decimal("2"),
            product_warehouse=product_wh,
            material_warehouse=material_wh,
        )

        disassembly.conduct()

        finished_qty = ProductStock.objects.get(warehouse=product_wh, product=finished).quantity
        material_qty = MaterialStock.objects.get(warehouse=material_wh, material=material).quantity
        material.refresh_from_db(fields=["current_stock"])
        disassembly.refresh_from_db()

        self.assertEqual(finished_qty, Decimal("1"))
        self.assertEqual(material_qty, Decimal("5"))
        self.assertEqual(material.current_stock, Decimal("4"))
        self.assertEqual(disassembly.status, ProductDisassembly.STATUS_COMPLETED)


class ProductionAssignmentFromOrderTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Order Link Org")
        self.product_wh = Warehouse.objects.create(name="Order Link WH Product", organization=self.org)
        self.material_wh = Warehouse.objects.create(name="Order Link WH Material", organization=self.org)
        self.tech_process = TechProcess.objects.create(name="Order Link TP")
        self.product = Product.objects.create(name="Order Link Product", min_stock=Decimal("0"))
        self.tech_card = TechCard.objects.create(
            name="Order Link TC",
            tech_process=self.tech_process,
            product=self.product,
        )
        self.order = Order.objects.create(customer_name="Client A")
        self.order_item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=3,
        )

    def test_create_from_order_item_creates_assignment_and_item(self):
        assignment, created = ProductionAssignment.create_from_order_item(
            self.order_item,
            product_warehouse=self.product_wh,
            material_warehouse=self.material_wh,
        )

        self.assertTrue(created)
        self.assertEqual(assignment.order_id, self.order.pk)
        self.assertEqual(assignment.order_item_id, self.order_item.pk)
        self.assertEqual(assignment.tech_process_id, self.tech_process.pk)
        self.assertEqual(assignment.items.count(), 1)
        self.assertEqual(assignment.items.first().quantity_planned, Decimal("3"))

    def test_create_from_order_item_reuses_active_assignment(self):
        first, created_first = ProductionAssignment.create_from_order_item(
            self.order_item,
            product_warehouse=self.product_wh,
            material_warehouse=self.material_wh,
        )
        second, created_second = ProductionAssignment.create_from_order_item(
            self.order_item,
            product_warehouse=self.product_wh,
            material_warehouse=self.material_wh,
        )

        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.pk, second.pk)


class ProductionAssignmentSupplyAdminTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Supply Admin Org")
        self.product_wh = Warehouse.objects.create(name="Supply Product WH", organization=self.org)
        self.material_wh = Warehouse.objects.create(name="Supply Material WH", organization=self.org)

        self.finished_product = Product.objects.create(name="Supply Finished", min_stock=Decimal("0"))
        self.component_product = Product.objects.create(name="Supply Component", min_stock=Decimal("0"))
        self.material = Material.objects.create(
            name="Supply Material",
            unit="шт",
        )
        self.supplier = Organization.objects.create(
            name="Supply Supplier",
            is_supplier=True,
            is_buyer=False,
        )
        self.tp = TechProcess.objects.create(name="Supply TP")
        self.main_tc = TechCard.objects.create(
            name="Main TC Supply",
            tech_process=self.tp,
            product=self.finished_product,
        )
        self.component_tc = TechCard.objects.create(
            name="Component TC Supply",
            tech_process=self.tp,
            product=self.component_product,
        )
        TechCardItem.objects.create(
            tech_card=self.main_tc,
            product=self.component_product,
            quantity=Decimal("2"),
            item_kind=TechCardItem.KIND_COMPONENT,
        )
        TechCardItem.objects.create(
            tech_card=self.main_tc,
            material=self.material,
            quantity=Decimal("4"),
        )
        MaterialStock.objects.create(
            warehouse=self.material_wh,
            material=self.material,
            quantity=Decimal("5"),
        )
        self.assignment = ProductionAssignment.objects.create(
            product_warehouse=self.product_wh,
            material_warehouse=self.material_wh,
        )
        ProductionAssignmentItem.objects.create(
            assignment=self.assignment,
            tech_card=self.main_tc,
            quantity_planned=Decimal("3"),
            sequence=1,
        )

        User = get_user_model()
        self.admin_user = User.objects.create_superuser(
            username="supply_admin",
            email="supply_admin@example.com",
            password="test-pass-123",
        )
        self.client.force_login(self.admin_user)

    def test_create_supply_admin_view_creates_assignment_and_redirects_to_it(self):
        url = reverse("admin:core_productionassignment_create_supply", args=[self.assignment.pk])
        response = self.client.post(url, follow=False)

        self.assignment.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(self.assignment.supply_assignment_id)
        self.assertEqual(
            response["Location"],
            reverse("admin:core_productionassignment_change", args=[self.assignment.supply_assignment_id]),
        )
        self.assertEqual(self.assignment.supply_assignment.items.count(), 1)
        self.assertEqual(
            self.assignment.supply_assignment.items.first().quantity_planned,
            Decimal("6"),
        )

    def test_create_supply_admin_view_redirects_existing_supply(self):
        created = self.assignment.create_supply_assignment()
        url = reverse("admin:core_productionassignment_create_supply", args=[self.assignment.pk])
        response = self.client.post(url, follow=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("admin:core_productionassignment_change", args=[created.pk]),
        )

    def test_supply_screen_shows_material_deficit_and_components(self):
        url = reverse("admin:core_productionassignment_supply", args=[self.assignment.pk])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Supply Material")
        self.assertContains(response, "Supply Component")
        self.assertEqual(response.context["material_deficit_rows"][0]["order_qty"], Decimal("7"))

    def test_supply_screen_creates_supplier_purchase_order_for_material_deficit(self):
        from procurement.models import SupplierPurchaseOrder

        url = reverse("admin:core_productionassignment_supply", args=[self.assignment.pk])
        response = self.client.post(
            url,
            {
                "action": "create_supplier_po",
                "supplier": str(self.supplier.pk),
                "material": [str(self.material.pk)],
            },
            follow=False,
        )

        purchase_order = SupplierPurchaseOrder.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("admin:procurement_supplierpurchaseorder_change", args=[purchase_order.pk]),
        )
        self.assertEqual(purchase_order.supplier_id, self.supplier.pk)
        line = purchase_order.lines.get()
        self.assertEqual(line.material_id, self.material.pk)
        self.assertEqual(line.quantity, Decimal("7.0000"))


class TechCardAdminFormTests(TestCase):
    def test_techcard_name_is_hidden_and_filled_from_product(self):
        from django.forms import HiddenInput
        from production.admin import TechCardAdminForm

        product = Product.objects.create(name="Табличка Баня из фанеры 3 мм", min_stock=Decimal("0"))
        tech_process = TechProcess.objects.create(name="Резка табличек")
        form = TechCardAdminForm(
            data={
                "name": "",
                "product": str(product.pk),
                "tech_process": str(tech_process.pk),
                "card_group": "",
                "allocate_cost": "",
                "description": "",
            }
        )

        self.assertIsInstance(form.fields["name"].widget, HiddenInput)
        self.assertIn("Техпроцесс — это маршрут изготовления", form.fields["tech_process"].help_text)
        self.assertIn("общую себестоимость нужно распределить", form.fields["allocate_cost"].help_text)
        self.assertTrue(form.is_valid(), form.errors.as_text())
        self.assertEqual(form.cleaned_data["name"], product.name)

    def test_techcard_group_is_not_shown_in_admin_fieldset(self):
        from production.admin import TechCardAdmin

        main_fields = TechCardAdmin.fieldsets[0][1]["fields"]
        self.assertNotIn("card_group", main_fields)

    def test_labor_inline_hides_employee_rate_column(self):
        from production.admin import TechCardLaborLineInline

        self.assertNotIn("employee_hourly_rate_display", TechCardLaborLineInline.fields)
        self.assertNotIn("employee_hourly_rate_display", TechCardLaborLineInline.readonly_fields)

    def test_material_kind_lines_included_in_planned_material_cost(self):
        product = Product.objects.create(name="Табличка материал kind", min_stock=Decimal("0"))
        tech_process = TechProcess.objects.create(name="TP material kind")
        stage = ProductionStage.objects.create(name="Резка", sequence=1)
        TechProcessStage.objects.create(tech_process=tech_process, production_stage=stage, order=1)
        tech_card = TechCard.objects.create(
            name=product.name,
            product=product,
            tech_process=tech_process,
        )
        material = Material.objects.create(name="Фанера kind", unit="лист")
        MaterialBatch.objects.create(
            material=material,
            movement_type=MaterialBatch.INCOMING,
            quantity=Decimal("10"),
            unit_price=Decimal("200"),
        )
        TechCardItem.objects.create(
            tech_card=tech_card,
            production_stage=stage,
            item_kind=TechCardItem.KIND_MATERIAL,
            material=material,
            quantity=Decimal("1.5"),
        )
        self.assertEqual(tech_card.planned_material_cost_per_unit(), Decimal("300.00"))

    def test_purchase_price_counts_when_no_receipts(self):
        product = Product.objects.create(name="Табличка без приёмки", min_stock=Decimal("0"))
        tech_process = TechProcess.objects.create(name="TP no receipt")
        stage = ProductionStage.objects.create(name="Шлифование", sequence=1)
        TechProcessStage.objects.create(tech_process=tech_process, production_stage=stage, order=1)
        tech_card = TechCard.objects.create(
            name=product.name,
            product=product,
            tech_process=tech_process,
        )
        material = Material.objects.create(
            name="Круг без приёмки",
            unit="шт",
            purchase_price=Decimal("45.50"),
        )
        TechCardItem.objects.create(
            tech_card=tech_card,
            production_stage=stage,
            item_kind=TechCardItem.KIND_MATERIAL,
            material=material,
            quantity=Decimal("0.3000"),
        )
        self.assertIsNone(material.average_price)
        self.assertEqual(material.cost_unit_price, Decimal("45.5000"))
        self.assertEqual(tech_card.planned_material_cost_per_unit(), Decimal("13.65"))

    def test_receipt_average_overrides_card_purchase_price(self):
        material = Material.objects.create(
            name="Фанера с карточкой и приёмкой",
            unit="лист",
            purchase_price=Decimal("100"),
        )
        MaterialBatch.objects.create(
            material=material,
            movement_type=MaterialBatch.INCOMING,
            quantity=Decimal("2"),
            unit_price=Decimal("200"),
        )
        self.assertEqual(material.average_price, Decimal("200.0000"))
        self.assertEqual(material.cost_unit_price, Decimal("200.0000"))

    def test_money_tab_json_includes_employee_hourly_rate(self):
        product = Product.objects.create(name="Табличка JSON", min_stock=Decimal("0"))
        tech_process = TechProcess.objects.create(name="TP JSON")
        employee = Employee.objects.create(
            full_name="Шлифовщик",
            hourly_rate=Decimal("450"),
        )
        stage = ProductionStage.objects.create(
            name="Шлифование материала",
            sequence=1,
            hourly_rate=Decimal("35"),
            master=employee,
        )
        TechProcessStage.objects.create(
            tech_process=tech_process,
            production_stage=stage,
            order=1,
        )
        tech_card = TechCard.objects.create(
            name=product.name,
            product=product,
            tech_process=tech_process,
        )
        from production.admin import TechCardAdmin

        stage_map = TechCardAdmin._tech_process_stages_map()
        rows = stage_map[str(tech_process.pk)]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["employee_hourly_rate"], "450.00")

        User = get_user_model()
        admin_user = User.objects.create_superuser(
            username="money_json_admin",
            email="money_json_admin@example.com",
            password="test-pass-123",
        )
        self.client.force_login(admin_user)
        TechCardLaborLine.objects.create(
            tech_card=tech_card,
            production_stage=stage,
            norm_hours=Decimal("0.1"),
            employee_minutes=Decimal("12"),
        )
        response = self.client.get(
            reverse("admin:production_techcardproxy_change", args=[tech_card.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "450")
        self.assertContains(response, "90.00")

    def test_material_picker_search_is_case_insensitive_for_russian_text(self):
        Material.objects.create(name="Фанера ФК 3 мм шлифованная", unit="лист")
        User = get_user_model()
        admin_user = User.objects.create_superuser(
            username="material_picker_admin",
            email="material_picker_admin@example.com",
            password="test-pass-123",
        )
        self.client.force_login(admin_user)

        response = self.client.get(
            reverse("admin:production_techcardproxy_material_picker_items"),
            {"group": "all", "q": "фанера", "page": "1", "page_size": "10"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(payload["total"], 1)
        self.assertIn("Фанера ФК 3 мм шлифованная", [row["name"] for row in payload["results"]])

    def test_money_tab_shows_missing_tech_process_stages_as_empty_rows(self):
        product = Product.objects.create(name="Табличка с этапами", min_stock=Decimal("0"))
        tech_process = TechProcess.objects.create(name="Маршрут таблички")
        stage_grave = ProductionStage.objects.create(name="Лазерная гравировка", sequence=1)
        stage_cut = ProductionStage.objects.create(name="Лазерная резка", sequence=2)
        TechProcessStage.objects.create(
            tech_process=tech_process,
            production_stage=stage_grave,
            order=1,
        )
        TechProcessStage.objects.create(
            tech_process=tech_process,
            production_stage=stage_cut,
            order=2,
        )
        tech_card = TechCard.objects.create(
            name=product.name,
            product=product,
            tech_process=tech_process,
        )
        User = get_user_model()
        admin_user = User.objects.create_superuser(
            username="money_tab_admin",
            email="money_tab_admin@example.com",
            password="test-pass-123",
        )
        self.client.force_login(admin_user)

        response = self.client.get(
            reverse("admin:production_techcardproxy_change", args=[tech_card.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Лазерная гравировка")
        self.assertContains(response, "Лазерная резка")
        self.assertEqual(tech_card.labor_lines.count(), 0)

    def test_money_tab_stages_follow_tech_process_order(self):
        import re

        product = Product.objects.create(name="Табличка порядок этапов", min_stock=Decimal("0"))
        tech_process = TechProcess.objects.create(name="Маршрут порядок")
        stage_sand = ProductionStage.objects.create(name="Шлифование материала", sequence=1)
        stage_cut = ProductionStage.objects.create(name="Лазерная резка", sequence=2)
        stage_grave = ProductionStage.objects.create(name="Лазерная гравировка", sequence=3)
        TechProcessStage.objects.create(tech_process=tech_process, production_stage=stage_sand, order=1)
        TechProcessStage.objects.create(tech_process=tech_process, production_stage=stage_cut, order=2)
        TechProcessStage.objects.create(tech_process=tech_process, production_stage=stage_grave, order=3)
        tech_card = TechCard.objects.create(
            name=product.name,
            product=product,
            tech_process=tech_process,
        )
        TechCardLaborLine.objects.create(
            tech_card=tech_card,
            production_stage=stage_grave,
            norm_hours=Decimal("0.1"),
        )
        TechCardLaborLine.objects.create(
            tech_card=tech_card,
            production_stage=stage_cut,
            norm_hours=Decimal("0.2"),
        )
        User = get_user_model()
        admin_user = User.objects.create_superuser(
            username="money_order_admin",
            email="money_order_admin@example.com",
            password="test-pass-123",
        )
        self.client.force_login(admin_user)

        response = self.client.get(
            reverse("admin:production_techcardproxy_change", args=[tech_card.pk])
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        tbody_m = re.search(
            r'<table class="tc-labor-inline-table".*?<tbody>(.*?)</tbody>',
            html,
            re.S,
        )
        self.assertIsNotNone(tbody_m)
        tbody = tbody_m.group(1)
        names = []
        for row_m in re.finditer(r'<tr class="form-row[^"]*"[^>]*>(.*?)</tr>', tbody, re.S):
            row_html = row_m.group(1)
            if "empty-form" in row_m.group(0):
                continue
            sel_m = re.search(
                r'name="labor_lines-\d+-production_stage"[^>]*>(.*?)</select>',
                row_html,
                re.S,
            )
            if not sel_m:
                continue
            opt_m = re.search(
                r'<option value="\d+" selected(?:="selected")?[^>]*>([^<]+)</option>',
                sel_m.group(1),
            )
            if opt_m:
                names.append(opt_m.group(1).strip())
        self.assertEqual(
            names,
            ["Шлифование материала", "Лазерная резка", "Лазерная гравировка"],
        )

    def test_labor_norms_save_via_admin_post(self):
        import re

        product = Product.objects.create(name="Табличка нормы POST", min_stock=Decimal("0"))
        tech_process = TechProcess.objects.create(name="Маршрут нормы POST")
        stage_a = ProductionStage.objects.create(name="Этап A POST", sequence=1, hourly_rate=Decimal("100"))
        stage_b = ProductionStage.objects.create(name="Этап B POST", sequence=2, hourly_rate=Decimal("50"))
        TechProcessStage.objects.create(tech_process=tech_process, production_stage=stage_a, order=1)
        TechProcessStage.objects.create(tech_process=tech_process, production_stage=stage_b, order=2)
        tech_card = TechCard.objects.create(
            name=product.name,
            product=product,
            tech_process=tech_process,
        )
        User = get_user_model()
        admin_user = User.objects.create_superuser(
            username="labor_save_admin",
            email="labor_save_admin@example.com",
            password="test-pass-123",
        )
        self.client.force_login(admin_user)
        url = reverse("admin:production_techcardproxy_change", args=[tech_card.pk])
        get_resp = self.client.get(url)
        self.assertEqual(get_resp.status_code, 200)
        html = get_resp.content.decode("utf-8")
        csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
        self.assertIsNotNone(csrf)
        prefix_m = re.search(r'name="([^"]+)-TOTAL_FORMS" value="(\d+)"', html)
        labor_prefix = None
        labor_total = 0
        for m in re.finditer(r'name="([^"]+)-TOTAL_FORMS" value="(\d+)"', html):
            if m.group(1).endswith("labor_lines") or m.group(1) == "labor_lines":
                labor_prefix = m.group(1)
                labor_total = int(m.group(2))
        self.assertEqual(labor_prefix, "labor_lines")
        self.assertEqual(labor_total, 2)

        post = {"csrfmiddlewaretoken": csrf.group(1)}
        for m in re.finditer(
            r'<input[^>]+name="([^"]+)"[^>]*value="([^"]*)"[^>]*>',
            html,
        ):
            name, val = m.group(1), m.group(2)
            if any(
                name.endswith(suffix)
                for suffix in ("-TOTAL_FORMS", "-INITIAL_FORMS", "-MIN_NUM_FORMS", "-MAX_NUM_FORMS")
            ):
                post[name] = val
            elif name in ("name", "allocate_cost", "description"):
                post[name] = val
        for m in re.finditer(r'<select[^>]+name="([^"]+)"[^>]*>(.*?)</select>', html, re.S):
            name, body = m.group(1), m.group(2)
            if name not in ("product", "tech_process"):
                continue
            sel = re.search(r'<option[^>]+selected[^>]+value="([^"]*)"', body) or re.search(
                r'<option value="([^"]*)"[^>]*selected', body
            )
            if sel:
                post[name] = sel.group(1)

        post["labor_norm_input_unit"] = "minutes"
        for i, stage in enumerate((stage_a, stage_b)):
            post[f"labor_lines-{i}-production_stage"] = str(stage.pk)
            post[f"labor_lines-{i}-norm_hours"] = "6" if i == 0 else "12"
            post[f"labor_lines-{i}-employee_minutes"] = "5" if i == 0 else "10"
            post[f"labor_lines-{i}-overhead_per_unit"] = "0"
            post.setdefault(f"labor_lines-{i}-id", "")

        save_resp = self.client.post(url, post, follow=True)
        self.assertEqual(save_resp.status_code, 200)
        self.assertEqual(tech_card.labor_lines.count(), 2)
        line_a = tech_card.labor_lines.get(production_stage=stage_a)
        line_b = tech_card.labor_lines.get(production_stage=stage_b)
        self.assertEqual(line_a.norm_hours, Decimal("0.1000"))
        self.assertEqual(line_b.norm_hours, Decimal("0.2000"))
        self.assertEqual(line_a.employee_minutes, Decimal("5.00"))
        self.assertEqual(line_b.employee_minutes, Decimal("10.00"))
        tech_card.refresh_from_db()
        self.assertEqual(tech_card.labor_norm_input_unit, TechCard.LABOR_NORM_INPUT_MINUTES)

    def test_planned_labor_is_employee_machine_goes_to_overhead(self):
        product = Product.objects.create(name="Табличка с трудом", min_stock=Decimal("0"))
        tech_process = TechProcess.objects.create(name="Маршрут с трудом")
        employee = Employee.objects.create(
            full_name="Мастер лазера",
            hourly_rate=Decimal("500"),
        )
        stage = ProductionStage.objects.create(
            name="Лазерная гравировка",
            sequence=1,
            hourly_rate=Decimal("800"),
            master=employee,
        )
        TechProcessStage.objects.create(
            tech_process=tech_process,
            production_stage=stage,
            order=1,
        )
        tech_card = TechCard.objects.create(
            name=product.name,
            product=product,
            tech_process=tech_process,
        )
        TechCardLaborLine.objects.create(
            tech_card=tech_card,
            production_stage=stage,
            norm_hours=Decimal("0.0833"),
            employee_minutes=Decimal("10"),
        )

        self.assertEqual(tech_card.planned_labor_cost_per_unit(), Decimal("83.33"))
        self.assertEqual(tech_card.planned_machine_cost_per_unit(), Decimal("66.64"))
        self.assertEqual(tech_card.planned_overhead_per_unit(), Decimal("66.64"))

    def test_techcard_planned_total_cost_includes_all_parts(self):
        product = Product.objects.create(name="Табличка полная себест.", min_stock=Decimal("0"))
        tech_process = TechProcess.objects.create(name="Маршрут полной себест.")
        employee = Employee.objects.create(full_name="Мастер", hourly_rate=Decimal("500"))
        stage = ProductionStage.objects.create(
            name="Лазерная резка",
            sequence=1,
            hourly_rate=Decimal("800"),
            cut_rate_per_meter=Decimal("10"),
            master=employee,
        )
        TechProcessStage.objects.create(tech_process=tech_process, production_stage=stage, order=1)
        tech_card = TechCard.objects.create(
            name=product.name,
            product=product,
            tech_process=tech_process,
        )
        material = Material.objects.create(name="Фанера 3мм", unit="лист")
        MaterialBatch.objects.create(
            material=material,
            movement_type=MaterialBatch.INCOMING,
            quantity=Decimal("10"),
            unit_price=Decimal("100"),
        )
        TechCardItem.objects.create(
            tech_card=tech_card,
            production_stage=stage,
            item_kind=TechCardItem.KIND_MATERIAL,
            material=material,
            quantity=Decimal("0.5"),
            cut_length_meters_per_unit=Decimal("2"),
        )
        TechCardLaborLine.objects.create(
            tech_card=tech_card,
            production_stage=stage,
            norm_hours=Decimal("0.1"),
            employee_minutes=Decimal("10"),
            overhead_per_unit=Decimal("5"),
        )
        self.assertEqual(tech_card.planned_material_cost_per_unit(), Decimal("50.00"))
        self.assertEqual(tech_card.planned_cut_cost_per_unit(), Decimal("20.00"))
        self.assertEqual(tech_card.planned_labor_cost_per_unit(), Decimal("83.33"))
        self.assertEqual(tech_card.planned_overhead_per_unit(), Decimal("85.00"))
        total = tech_card.planned_total_cost_per_unit()
        self.assertEqual(total, Decimal("238.33"))
        tech_card.sync_material_norms_to_product()
        product.refresh_from_db()
        self.assertEqual(product.planned_total_cost, total)

    def test_planned_total_includes_component_tech_card_cost(self):
        sanded = Product.objects.create(name="Шлифованный лист тест", min_stock=Decimal("0"))
        primed = Product.objects.create(name="Грунтованный лист тест", min_stock=Decimal("0"))
        employee = Employee.objects.create(full_name="Мастер сушки", hourly_rate=Decimal("600"))
        stage_sand = ProductionStage.objects.create(
            name="Шлиф тест", sequence=1, hourly_rate=Decimal("500"), master=employee
        )
        stage_coat = ProductionStage.objects.create(
            name="Грунт тест", sequence=2, hourly_rate=Decimal("500"), master=employee
        )
        process_a = TechProcess.objects.create(name="Процесс шлиф тест")
        process_b = TechProcess.objects.create(name="Процесс грунт тест")
        TechProcessStage.objects.create(tech_process=process_a, production_stage=stage_sand, order=1)
        TechProcessStage.objects.create(tech_process=process_b, production_stage=stage_coat, order=1)
        card_a = TechCard.objects.create(name="Карта A тест", tech_process=process_a, product=sanded)
        TechCardLaborLine.objects.create(
            tech_card=card_a,
            production_stage=stage_sand,
            norm_hours=Decimal("0.1"),
            employee_minutes=Decimal("6"),
        )
        card_b = TechCard.objects.create(name="Карта B тест", tech_process=process_b, product=primed)
        TechCardItem.objects.create(
            tech_card=card_b,
            product=sanded,
            quantity=Decimal("1"),
            item_kind=TechCardItem.KIND_COMPONENT,
            component_tech_card=card_a,
        )
        TechCardLaborLine.objects.create(
            tech_card=card_b,
            production_stage=stage_coat,
            norm_hours=Decimal("0.05"),
            overhead_per_unit=Decimal("40"),
        )
        sand_cost = card_a.planned_total_cost_per_unit()
        self.assertGreater(sand_cost, Decimal("0"))
        self.assertEqual(card_b.planned_component_cost_per_unit(), sand_cost)
        self.assertEqual(
            card_b.planned_total_cost_per_unit(),
            sand_cost
            + card_b.planned_labor_cost_per_unit()
            + card_b.planned_overhead_per_unit(),
        )
        self.assertEqual(
            card_b.planned_overhead_per_unit(),
            Decimal("40.00") + card_b.planned_machine_cost_per_unit(),
        )


class OrderItemAutoPriceTests(TestCase):
    def test_order_item_uses_product_planned_price_when_present(self):
        product = Product.objects.create(
            name="Готовое изделие",
            planned_price=Decimal("590.00"),
            min_stock=Decimal("0"),
        )
        order = Order.objects.create(customer_name="Client Price")
        item = OrderItem.objects.create(
            order=order,
            product=product,
            quantity=1,
            planned_price=None,
        )
        self.assertEqual(item.planned_price, Decimal("590.00"))

    def test_order_item_calculates_price_from_costs_markup_and_rounding(self):
        product = Product.objects.create(
            name="Салфетница 3мм",
            planned_markup_percent=Decimal("50"),
            min_stock=Decimal("0"),
        )
        material = Material.objects.create(name="Фанера 3мм", unit="м2")
        MaterialBatch.objects.create(
            material=material,
            movement_type=MaterialBatch.INCOMING,
            quantity=Decimal("10"),
            unit_price=Decimal("95"),
        )
        ProductMaterial.objects.create(
            product=product,
            material=material,
            quantity_per_unit=Decimal("1"),
        )
        order = Order.objects.create(customer_name="Client Calc")
        item = OrderItem.objects.create(
            order=order,
            product=product,
            quantity=2,
            planned_price=None,
        )
        # Себестоимость 95.00, +50% = 142.50, округление вверх до шага 10 => 150.00
        self.assertEqual(item.planned_price, Decimal("150.00"))


class ProductModificationPricingTests(TestCase):
    def test_modification_sale_price_uses_factor_and_product_markup(self):
        product = Product.objects.create(
            name="Основа",
            planned_markup_percent=Decimal("30"),
            min_stock=Decimal("0"),
        )
        material = Material.objects.create(name="Материал М", unit="шт")
        MaterialBatch.objects.create(
            material=material,
            movement_type=MaterialBatch.INCOMING,
            quantity=Decimal("10"),
            unit_price=Decimal("100"),
        )
        ProductMaterial.objects.create(
            product=product,
            material=material,
            quantity_per_unit=Decimal("1"),
        )
        mod = ProductModification.objects.create(
            product=product,
            name="Большая",
            quantity_factor=Decimal("1.5"),
        )
        # База 100 * 1.5 = 150; +30% => 195; округление вверх до 10 => 200
        self.assertEqual(mod.planned_cost, Decimal("150.00"))
        self.assertEqual(mod.sale_price, Decimal("200.00"))

    def test_modification_name_autobuild_from_compact_params(self):
        product = Product.objects.create(name="Основа 2", min_stock=Decimal("0"))
        mod = ProductModification.objects.create(
            product=product,
            thickness_mm=3,
            grade=ProductModification.GRADE_22,
            sanding_sides=ProductModification.SANDING_TWO_SIDE,
            abrasive_grit="p120",
        )
        self.assertEqual(mod.name, "3 мм | сорт 2/2 | Ш2 | P120")


class ProductionExpectationStockReportTests(TestCase):
    """S2: плановый выпуск (флажок «Ожидание») в отчётах закупок и остатков."""

    def setUp(self):
        self.org = Organization.objects.create(name="Org Expectation")
        self.product_wh = Warehouse.objects.create(name="WH Product", organization=self.org)
        self.material_wh = Warehouse.objects.create(name="WH Material", organization=self.org)
        self.product = Product.objects.create(
            name="Баня настольная",
            product_kind=Product.PRODUCT_KIND_GOODS,
            min_stock=Decimal("0"),
        )
        self.other_wh = Warehouse.objects.create(name="WH Other", organization=self.org)
        self.tech_process = TechProcess.objects.create(name="TP Expectation")
        self.tech_card = TechCard.objects.create(
            name=self.product.name,
            product=self.product,
            tech_process=self.tech_process,
        )

    def _assignment_with_pending(self, *, planned=Decimal("10"), produced=Decimal("3"), expectation=True):
        assignment = ProductionAssignment.objects.create(
            product_warehouse=self.product_wh,
            material_warehouse=self.material_wh,
            status=ProductionAssignment.STATUS_IN_PROGRESS,
            expectation=expectation,
        )
        ProductionAssignmentItem.objects.create(
            assignment=assignment,
            tech_card=self.tech_card,
            quantity_planned=planned,
            quantity_produced=produced,
            sequence=1,
        )
        return assignment

    def test_pending_production_by_product_counts_planned_minus_good(self):
        self._assignment_with_pending(planned=Decimal("10"), produced=Decimal("3"))
        from core.services.production_stock_reports import pending_production_by_product

        pending = pending_production_by_product()
        self.assertEqual(pending.get(self.product.pk), Decimal("7"))

    def test_pending_production_ignores_completed_and_disabled_expectation(self):
        self._assignment_with_pending(expectation=False)
        completed = ProductionAssignment.objects.create(
            product_warehouse=self.product_wh,
            material_warehouse=self.material_wh,
            status=ProductionAssignment.STATUS_COMPLETED,
            expectation=True,
        )
        ProductionAssignmentItem.objects.create(
            assignment=completed,
            tech_card=self.tech_card,
            quantity_planned=Decimal("5"),
            quantity_produced=Decimal("0"),
            sequence=1,
        )
        from core.services.production_stock_reports import pending_production_by_product

        self.assertEqual(pending_production_by_product(), {})

    def test_pending_production_scoped_by_warehouse(self):
        self._assignment_with_pending(planned=Decimal("4"), produced=Decimal("1"))
        other_assignment = ProductionAssignment.objects.create(
            product_warehouse=self.other_wh,
            material_warehouse=self.material_wh,
            status=ProductionAssignment.STATUS_DRAFT,
            expectation=True,
        )
        ProductionAssignmentItem.objects.create(
            assignment=other_assignment,
            tech_card=self.tech_card,
            quantity_planned=Decimal("8"),
            quantity_produced=Decimal("0"),
            sequence=1,
        )
        from core.services.production_stock_reports import pending_production_by_product

        by_wh = pending_production_by_product(warehouse_id=self.product_wh.pk)
        self.assertEqual(by_wh.get(self.product.pk), Decimal("3"))
        total = pending_production_by_product()
        self.assertEqual(total.get(self.product.pk), Decimal("11"))

    def test_purchase_management_admin_includes_production_pending(self):
        self._assignment_with_pending(planned=Decimal("6"), produced=Decimal("2"))
        ProductStock.objects.create(
            warehouse=self.product_wh,
            product=self.product,
            quantity=Decimal("1"),
        )
        from procurement.admin import PurchaseManagementProductAdmin
        from procurement.models import PurchaseManagementProduct

        admin_obj = PurchaseManagementProductAdmin(PurchaseManagementProduct, admin.site)
        row = admin_obj.get_queryset(request=None).get(pk=self.product.pk)
        self.assertEqual(row._prod_pending, Decimal("4"))
        self.assertEqual(row._coverage_for_days, Decimal("5"))

    def test_product_stock_admin_shows_production_pending(self):
        self._assignment_with_pending(planned=Decimal("5"), produced=Decimal("1"))
        stock = ProductStock.objects.create(
            warehouse=self.product_wh,
            product=self.product,
            quantity=Decimal("2"),
        )
        from core.admin import ProductStockAdmin

        admin_obj = ProductStockAdmin(ProductStock, admin.site)
        row = admin_obj.get_queryset(request=None).get(pk=stock.pk)
        self.assertEqual(row._prod_pending, Decimal("4"))
        self.assertEqual(row._effective_qty, Decimal("6"))


class MaterialAdminAutocompleteTests(TestCase):
    def setUp(self):
        Material.objects.create(name="Плёнка упаковочная 50 см", unit="м", material_type="упаковка")
        User = get_user_model()
        self.admin_user = User.objects.create_superuser(
            username="material_ac_admin",
            email="material_ac_admin@example.com",
            password="test-pass-123",
        )
        self.client.force_login(self.admin_user)
        self.url = reverse("admin:autocomplete")

    def _autocomplete(self, term: str):
        return self.client.get(
            self.url,
            {
                "term": term,
                "app_label": "procurement",
                "model_name": "goodsreceiptline",
                "field_name": "material",
            },
        )

    def test_material_autocomplete_is_case_insensitive_for_russian(self):
        for term in ("плёнка", "Плёнка", "пленка", "ПЛЕНКА", "упаковочная"):
            response = self._autocomplete(term)
            self.assertEqual(response.status_code, 200, msg=term)
            texts = [row["text"] for row in response.json()["results"]]
            self.assertTrue(
                any("упаковочная" in text.casefold() for text in texts),
                msg=term,
            )


class MaterialGroupCardHelpersTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin_user = User.objects.create_superuser(
            username="material_group_admin",
            email="material_group_admin@example.com",
            password="test-pass-123",
        )
        self.client.force_login(self.admin_user)
        self.plywood = MaterialGroup.objects.create(name="Фанера", has_grade=True)
        self.acrylic = MaterialGroup.objects.create(name="Акрил", has_grade=False)
        self.packaging = MaterialGroup.objects.create(
            name="Упаковка", has_grade=False, has_sheet_size=False
        )
        MaterialGroupType.objects.create(group=self.plywood, name="ФК", sort_order=0)
        MaterialGroupType.objects.create(group=self.plywood, name="ФСФ", sort_order=1)
        MaterialGroupType.objects.create(group=self.acrylic, name="прозрачный", sort_order=0)
        MaterialGroupType.objects.create(group=self.packaging, name="плёнка", sort_order=0)
        MaterialGroupType.objects.create(group=self.packaging, name="скотч", sort_order=1)

    def test_group_autocomplete_suggests_from_first_letter(self):
        url = reverse("admin:autocomplete")
        response = self.client.get(
            url,
            {
                "term": "ф",
                "app_label": "core",
                "model_name": "material",
                "field_name": "group",
            },
        )
        self.assertEqual(response.status_code, 200)
        texts = [row["text"] for row in response.json()["results"]]
        self.assertIn("Фанера", texts)
        self.assertNotIn("Акрил", texts)

    def test_group_meta_returns_types_and_grade_flag(self):
        url = reverse("admin:core_material_group_meta")
        plywood = self.client.get(url, {"group_id": self.plywood.pk})
        self.assertEqual(plywood.status_code, 200)
        data = plywood.json()
        self.assertTrue(data["has_grade"])
        self.assertTrue(data["has_sheet_size"])
        self.assertEqual(data["types"], ["ФК", "ФСФ"])
        self.assertIn("2/2", data["grades"])

        acrylic = self.client.get(url, {"group_id": self.acrylic.pk})
        self.assertEqual(acrylic.json()["has_grade"], False)
        self.assertEqual(acrylic.json()["types"], ["прозрачный"])
        self.assertEqual(acrylic.json()["grades"], [])
        self.assertTrue(acrylic.json()["has_sheet_size"])

        packing = self.client.get(url, {"group_id": self.packaging.pk})
        pack = packing.json()
        self.assertFalse(pack["has_grade"])
        self.assertFalse(pack["has_sheet_size"])
        self.assertEqual(pack["types"], ["плёнка", "скотч"])
        self.assertIn("рулон", pack["units"])
        self.assertIn("л", pack["units"])
        self.assertNotIn("лист", pack["units"])

        abrasives = MaterialGroup.objects.create(
            name="Абразивы", has_grade=False, has_sheet_size=False
        )
        abrasive_meta = self.client.get(url, {"group_id": abrasives.pk}).json()
        self.assertFalse(abrasive_meta["has_sheet_size"])
        self.assertFalse(abrasive_meta["has_grade"])
        self.assertEqual(abrasive_meta["types"], [])
        self.assertIn("шт", abrasive_meta["units"])
        self.assertNotIn("лист", abrasive_meta["units"])
        self.assertFalse(abrasive_meta["has_brand"])
        self.assertFalse(abrasive_meta["has_color"])
        self.assertFalse(abrasive_meta["has_grit"])
        self.assertFalse(abrasive_meta["has_diameter"])
        self.assertFalse(abrasive_meta["has_hole_count"])
        self.assertEqual(abrasive_meta["brands"], [])
        self.assertEqual(abrasive_meta["colors"], [])
        self.assertEqual(abrasive_meta["grits"], [])
        self.assertEqual(abrasive_meta["diameters"], [])
        self.assertEqual(abrasive_meta["holes"], [])

        coatings = MaterialGroup.objects.create(
            name="Покрытия",
            has_grade=False,
            has_sheet_size=False,
            has_brand=True,
            has_color=True,
        )
        MaterialGroupType.objects.create(group=coatings, name="морилка водная", sort_order=0)
        MaterialGroupType.objects.create(group=coatings, name="лак акриловый", sort_order=1)
        MaterialGroupBrand.objects.create(group=coatings, name="Tury", sort_order=0)
        MaterialGroupBrand.objects.create(group=coatings, name="Акватекс", sort_order=1)
        MaterialGroupColor.objects.create(group=coatings, name="Дуб", sort_order=0)
        MaterialGroupColor.objects.create(group=coatings, name="Сосна", sort_order=1)
        coat = self.client.get(url, {"group_id": coatings.pk}).json()
        self.assertTrue(coat["has_brand"])
        self.assertTrue(coat["has_color"])
        self.assertFalse(coat["has_grade"])
        self.assertEqual(coat["brands"], ["Tury", "Акватекс"])
        self.assertEqual(coat["colors"], ["Дуб", "Сосна"])
        self.assertIn("морилка водная", coat["types"])

    def test_packaging_form_uses_selects_with_group_choices(self):
        from core.admin import MaterialAdminForm

        material = Material.objects.create(
            name="Стретч",
            unit="м",
            material_type="плёнка",
            group=self.packaging,
        )
        form = MaterialAdminForm(instance=material)
        type_values = [choice[0] for choice in form.fields["material_type"].widget.choices]
        unit_values = [choice[0] for choice in form.fields["unit"].widget.choices]
        self.assertEqual(form.fields["material_type"].widget.input_type, "select")
        self.assertEqual(form.fields["unit"].widget.input_type, "select")
        self.assertIn("плёнка", type_values)
        self.assertIn("скотч", type_values)
        self.assertIn("рулон", unit_values)
        self.assertIn("м", unit_values)

    def test_bound_form_keeps_posted_type_and_unit(self):
        from core.admin import MaterialAdminForm

        material = Material.objects.create(
            name="Стретч",
            unit="м",
            material_type="плёнка",
            group=self.packaging,
        )
        form = MaterialAdminForm(
            data={
                "name": "Стретч",
                "group": str(self.packaging.pk),
                "material_type": "плёнка",
                "unit": "м",
                "grade": "",
            },
            instance=material,
        )
        type_values = [choice[0] for choice in form.fields["material_type"].widget.choices]
        self.assertIn("плёнка", type_values)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        material.refresh_from_db()
        self.assertEqual(material.unit, "м")
        self.assertEqual(material.material_type, "плёнка")

    def test_stain_form_builds_name_from_brand_and_color(self):
        from core.admin import MaterialAdminForm

        coatings = MaterialGroup.objects.create(
            name="Покрытия",
            has_grade=False,
            has_sheet_size=False,
            has_brand=True,
            has_color=True,
        )
        MaterialGroupType.objects.create(group=coatings, name="морилка водная", sort_order=0)
        MaterialGroupBrand.objects.create(group=coatings, name="Tury", sort_order=0)
        MaterialGroupColor.objects.create(group=coatings, name="Дуб", sort_order=0)
        form = MaterialAdminForm(
            data={
                "name": "",
                "group": str(coatings.pk),
                "material_type": "морилка водная",
                "brand": "Tury",
                "color": "Дуб",
                "unit": "л",
                "grade": "",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        material = form.save()
        self.assertEqual(material.name, "Морилка водная Tury «Дуб»")
        self.assertEqual(material.brand, "Tury")
        self.assertEqual(material.color, "Дуб")

        varnish = MaterialAdminForm(
            data={
                "name": "Лак паркетный Акватекс «матовый»",
                "group": str(coatings.pk),
                "material_type": "лак акриловый",
                "brand": "Акватекс",
                "color": "Дуб",
                "unit": "л",
                "grade": "",
            }
        )
        self.assertTrue(varnish.is_valid(), varnish.errors)
        saved = varnish.save()
        self.assertEqual(saved.brand, "Акватекс")
        self.assertEqual(saved.color, "")
        self.assertEqual(saved.name, "Лак паркетный Акватекс «матовый»")

    def test_abrasive_form_builds_disc_and_belt_names(self):
        from core.admin import MaterialAdminForm
        from core.models import MaterialGroupDiameter, MaterialGroupGrit, MaterialGroupHoleCount

        abrasives = MaterialGroup.objects.create(
            name="Абразивы",
            has_grade=False,
            has_sheet_size=False,
            has_brand=True,
            has_grit=True,
            has_diameter=True,
            has_hole_count=True,
        )
        MaterialGroupType.objects.create(group=abrasives, name="эксцентриковый", sort_order=0)
        MaterialGroupType.objects.create(group=abrasives, name="ленточный", sort_order=1)
        MaterialGroupBrand.objects.create(group=abrasives, name="Flexione", sort_order=0)
        MaterialGroupGrit.objects.create(group=abrasives, name="P150", sort_order=0)
        MaterialGroupDiameter.objects.create(group=abrasives, name="125", sort_order=0)
        MaterialGroupDiameter.objects.create(group=abrasives, name="150", sort_order=1)
        MaterialGroupHoleCount.objects.create(group=abrasives, name="8", sort_order=0)

        disc = MaterialAdminForm(
            data={
                "name": "",
                "group": str(abrasives.pk),
                "material_type": "эксцентриковый",
                "brand": "Flexione",
                "grit": "P150",
                "diameter_mm": "125",
                "hole_count": "8",
                "unit": "шт",
                "grade": "",
                "color": "",
            }
        )
        self.assertTrue(disc.is_valid(), disc.errors)
        saved_disc = disc.save()
        self.assertEqual(saved_disc.name, "Круг шлифовальный Flexione 125мм 8 отв. (P150)")
        self.assertEqual(saved_disc.grit, "P150")
        self.assertEqual(saved_disc.diameter_mm, "125")
        self.assertEqual(saved_disc.hole_count, "8")

        belt = MaterialAdminForm(
            data={
                "name": "",
                "group": str(abrasives.pk),
                "material_type": "ленточный",
                "brand": "Flexione",
                "grit": "p120",
                "diameter_mm": "125",
                "hole_count": "8",
                "unit": "шт",
                "grade": "",
                "color": "",
            }
        )
        self.assertTrue(belt.is_valid(), belt.errors)
        saved_belt = belt.save()
        self.assertEqual(saved_belt.name, "Лента шлифовальная Flexione (P120)")
        self.assertEqual(saved_belt.grit, "P120")

        url = reverse("admin:core_material_group_meta")
        meta = self.client.get(url, {"group_id": abrasives.pk}).json()
        self.assertTrue(meta["has_brand"])
        self.assertTrue(meta["has_grit"])
        self.assertTrue(meta["has_diameter"])
        self.assertTrue(meta["has_hole_count"])
        self.assertIn("Flexione", meta["brands"])
        self.assertIn("P150", meta["grits"])
        self.assertEqual(meta["diameters"], ["125", "150"])
        self.assertIn("8", meta["holes"])
        self.assertIn("эксцентриковый", meta["types"])
        self.assertIn("ленточный", meta["types"])

    def test_material_group_type_js_defines_stain_name_helper(self):
        from pathlib import Path

        from django.conf import settings

        js = Path(settings.BASE_DIR, "core/static/core/admin/material_group_type.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("function looksLikeStainName", js)
        self.assertIn("is-color-visible", js)
        self.assertIn("is-grade-visible", js)

    def test_kr_acrylic_primer_is_seeded_with_photo(self):
        from pathlib import Path

        from django.conf import settings

        seed = Path(settings.BASE_DIR) / "core" / "seed_media" / "primer_kr.png"
        self.assertTrue(seed.exists(), "нет файла фото грунта")
        primer = Material.objects.get(name="Грунт акриловый «глубокого проникновения»")
        self.assertEqual(primer.material_type, "грунт акриловый")
        self.assertEqual(primer.brand, "")
        self.assertEqual(primer.unit, "кг")
        self.assertEqual(primer.color, "")
        self.assertTrue(primer.photo)
        self.assertIn("primer_kr", primer.photo.name)

    def test_plywood_fk_4mm_is_seeded(self):
        names = [
            "Фанера ФК 900*600 сорт 2/2 4мм",
            "Фанера ФК 621*621 сорт 2/2 4мм",
            "Фанера ФК 317*900 сорт 2/2 4мм",
        ]
        rows = list(Material.objects.filter(name__in=names).order_by("name"))
        self.assertEqual(len(rows), 3)
        by_name = {row.name: row for row in rows}
        self.assertEqual(by_name[names[0]].thickness_mm, Decimal("4"))
        self.assertEqual(by_name[names[0]].sheet_length_mm, Decimal("900"))
        self.assertEqual(by_name[names[0]].sheet_width_mm, Decimal("600"))
        self.assertEqual(by_name[names[1]].sheet_length_mm, Decimal("621"))
        self.assertEqual(by_name[names[2]].sheet_length_mm, Decimal("900"))
        self.assertEqual(by_name[names[2]].sheet_width_mm, Decimal("317"))
        for row in rows:
            self.assertEqual(row.material_type, "Фанера ФК")
            self.assertEqual(row.unit, "лист")

    def test_fk_900x600x6_sanding_and_primer_tech_cards(self):
        sanded = Product.objects.get(name="Фанера ФК шлифованный 900×600 6 мм")
        primed = Product.objects.get(name="Фанера ФК грунтованный 900×600 6 мм")
        self.assertEqual(sanded.sheet_length_mm, Decimal("900"))
        self.assertEqual(sanded.sheet_width_mm, Decimal("600"))
        self.assertEqual(sanded.sheet_thickness_mm, Decimal("6"))
        self.assertEqual(primed.sheet_thickness_mm, Decimal("6"))
        self.assertEqual(sanded.product_group.name, "Фанера ФК шлифованный")
        self.assertEqual(primed.product_group.name, "Фанера ФК грунтованный")

        card_a = TechCard.objects.get(name="Шлифование ФК 900×600×6 Ш2 P120→P180")
        card_b = TechCard.objects.get(name="Грунтование ФК 900×600×6 Ш2 1 слой")
        self.assertEqual(card_a.product, sanded)
        self.assertEqual(card_b.product, primed)
        self.assertEqual(card_a.tech_process.name, "Шлифование абразивом P120->P180 с двух сторон")
        stages_a = [row.production_stage.name for row in card_a.tech_process.get_stages_ordered()]
        self.assertEqual(
            stages_a,
            ["Шлифование материала сторона 1", "Шлифование материала сторона 2"],
        )
        stages_b = [row.production_stage.name for row in card_b.tech_process.get_stages_ordered()]
        self.assertEqual(
            stages_b,
            [
                "Нанесение покрытия на материал слой 1 сторона 1",
                "Просушка нанесённого на материал покрытия сторона 1",
                "Нанесение покрытия на материал слой 1 сторона 2",
                "Просушка нанесённого на материал покрытия сторона 2",
                "Промежуточное шлифование после просушки 1 -го слоя покрытия",
            ],
        )

        plywood = Material.objects.get(name="Фанера ФК 900*600 сорт 2/2")
        p120 = Material.objects.get(name="Круг шлифовальный FLEXIONE 125мм 8 отв. (P120)")
        p180 = Material.objects.get(name="Круг шлифовальный FLEXIONE 125мм 8 отв. (P180)")
        p320 = Material.objects.get(name="Круг шлифовальный FLEXIONE 125мм 8 отв. (P320)")
        primer = Material.objects.get(name="Грунт акриловый «глубокого проникновения»")

        a_qty = card_a.material_quantities_per_unit_by_material_id()
        self.assertEqual(a_qty[plywood.pk], Decimal("1"))
        self.assertEqual(a_qty[p120.pk], Decimal("0.6"))
        self.assertEqual(a_qty[p180.pk], Decimal("0.6"))
        self.assertEqual(card_a.items.filter(material=plywood).count(), 1)
        self.assertEqual(card_a.items.filter(material=p120).count(), 2)
        self.assertEqual(card_a.labor_lines.count(), 2)

        component = card_b.items.get(item_kind=TechCardItem.KIND_COMPONENT)
        self.assertEqual(component.product, sanded)
        self.assertEqual(component.component_tech_card, card_a)
        b_qty = card_b.material_quantities_per_unit_by_material_id()
        self.assertEqual(b_qty[primer.pk], Decimal("0.10"))
        self.assertEqual(b_qty[p320.pk], Decimal("0.2"))
        self.assertEqual(card_b.labor_lines.count(), 5)
        dry1 = ProductionStage.objects.get(
            name="Просушка нанесённого на материал покрытия сторона 1"
        )
        dry2 = ProductionStage.objects.get(
            name="Просушка нанесённого на материал покрытия сторона 2"
        )
        self.assertEqual(dry1.hourly_rate, Decimal("0"))
        self.assertEqual(dry2.hourly_rate, Decimal("0"))
        self.assertEqual(card_b.labor_lines.get(production_stage=dry1).norm_hours, Decimal("1"))
        self.assertEqual(card_b.labor_lines.get(production_stage=dry2).norm_hours, Decimal("1"))
        self.assertEqual(
            card_b.labor_lines.get(production_stage=dry1).overhead_per_unit, Decimal("500")
        )
        self.assertEqual(
            card_b.labor_lines.get(production_stage=dry2).overhead_per_unit, Decimal("500")
        )
        self.assertEqual(
            card_b.planned_overhead_per_unit(),
            Decimal("1000.00") + card_b.planned_machine_cost_per_unit(),
        )
        self.assertEqual(card_b.planned_component_cost_per_unit(), card_a.planned_total_cost_per_unit())
        self.assertGreater(card_b.planned_total_cost_per_unit(), card_b.planned_overhead_per_unit())

    def test_photo_widget_does_not_show_file_path(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from core.admin import MaterialAdminForm

        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
            b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        material = Material.objects.create(
            name="Морилка тест",
            unit="л",
            group=self.packaging,
            photo=SimpleUploadedFile("stain_pine.png", png, content_type="image/png"),
        )
        html = str(MaterialAdminForm(instance=material)["photo"])
        self.assertIn("material-card-photo", html)
        self.assertIn("material-card-photo-link", html)
        self.assertIn("Заменить", html)
        self.assertIn("file-upload-label", html)
        self.assertIn("laser-file-input-native", html)
        self.assertNotIn("Choose File", html)
        self.assertNotIn("No file chosen", html)
        self.assertNotIn("На данный момент", html)
        self.assertNotIn("Текущий файл", html)

    def test_photo_widget_empty_uses_russian_file_labels(self):
        from core.admin import MaterialAdminForm

        html = str(MaterialAdminForm()["photo"])
        self.assertIn("Выберите файл", html)
        self.assertIn("Файл не выбран", html)
        self.assertIn("file-upload-input", html)
        self.assertNotIn("Choose File", html)
        self.assertNotIn("No file chosen", html)

    def test_group_field_keeps_label_in_row_not_legend(self):
        material = Material.objects.create(
            name="Фанера тест вёрстки",
            unit="лист",
            material_type="ФК",
            group=self.plywood,
        )
        url = reverse("admin:core_material_change", args=[material.pk])
        html = self.client.get(url).content.decode("utf-8")
        group_chunk = html.split('class="form-row field-group"', 1)[1].split(
            'class="form-row field-material_type"', 1
        )[0]
        self.assertNotIn("laser-related-fieldset", group_chunk)
        self.assertNotIn("<legend", group_chunk)
        self.assertIn('for="id_group"', group_chunk)
        self.assertIn("Группа", group_chunk)
        self.assertIn("<label", group_chunk)
        self.assertLess(
            group_chunk.find("<label"),
            group_chunk.find("related-widget-wrapper"),
        )
        self.assertIn("Выберите файл", html)
        self.assertIn("Файл не выбран", html)
        self.assertIn("admin_file_input_ru.js", html)
        self.assertIn("laser-file-input-native", html)

    def test_admin_file_widget_uses_russian_labels(self):
        from django.contrib.admin.widgets import AdminFileWidget

        html = AdminFileWidget().render(
            "invoice_file", None, attrs={"id": "id_invoice_file"}
        )
        self.assertIn("Выберите файл", html)
        self.assertIn("Файл не выбран", html)
        self.assertIn("laser-file-input-native", html)
        self.assertNotIn("Choose File", html)
        self.assertNotIn("No file chosen", html)
        self.assertNotIn("Currently:", html)

    def test_sheet_size_row_uses_compact_dst_labels(self):
        material = Material.objects.create(
            name="Фанера размеры",
            unit="лист",
            material_type="ФК",
            group=self.plywood,
        )
        url = reverse("admin:core_material_change", args=[material.pk])
        html = self.client.get(url).content.decode("utf-8")
        self.assertIn("Д×Ш×Т", html)
        self.assertIn('for="id_sheet_length_mm"', html)
        self.assertIn('for="id_sheet_width_mm"', html)
        self.assertIn('for="id_thickness_mm"', html)
        self.assertIn(">Ш:</label>", html)
        self.assertIn(">Т:</label>", html)
        self.assertIn(
            "Укажите Длину, Ширину и Толщину листа для расчёта площади.",
            html,
        )
        self.assertNotIn("Длина, мм:", html)
        self.assertNotIn("Ширина, мм:", html)
        self.assertNotIn("Толщина, мм:", html)

    def test_add_brand_and_color_to_group_list(self):
        coatings = MaterialGroup.objects.create(
            name="Покрытия",
            has_grade=False,
            has_sheet_size=False,
            has_brand=True,
            has_color=True,
        )
        url = reverse("admin:core_material_group_choice_add")
        brand = self.client.post(
            url,
            {"group_id": coatings.pk, "kind": "brand", "name": "Belinka"},
        )
        self.assertEqual(brand.status_code, 200, brand.content)
        self.assertEqual(brand.json()["name"], "Belinka")
        self.assertIn("Belinka", brand.json()["brands"])
        self.assertTrue(MaterialGroupBrand.objects.filter(group=coatings, name="Belinka").exists())

        color = self.client.post(
            url,
            {"group_id": coatings.pk, "kind": "color", "name": "Венге"},
        )
        self.assertEqual(color.status_code, 200, color.content)
        self.assertEqual(color.json()["name"], "Венге")
        self.assertTrue(MaterialGroupColor.objects.filter(group=coatings, name="Венге").exists())

        again = self.client.post(
            url,
            {"group_id": coatings.pk, "kind": "brand", "name": "belinka"},
        )
        self.assertEqual(again.json()["name"], "Belinka")
        self.assertEqual(MaterialGroupBrand.objects.filter(group=coatings).count(), 1)

        type_add = self.client.post(
            url,
            {"group_id": coatings.pk, "kind": "type", "name": "масло"},
        )
        self.assertEqual(type_add.status_code, 200, type_add.content)
        self.assertIn("масло", type_add.json()["types"])
        self.assertTrue(MaterialGroupType.objects.filter(group=coatings, name="масло").exists())

        MaterialGroupBrand.objects.create(group=coatings, name="Tury", sort_order=0)
        Material.objects.create(
            name="Морилка водная Tury «Дуб»",
            group=coatings,
            material_type="морилка водная",
            brand="Tury",
            color="Дуб",
            unit="л",
        )
        renamed = self.client.post(
            url,
            {
                "group_id": coatings.pk,
                "kind": "brand",
                "action": "rename",
                "old_name": "Tury",
                "name": "Tury Wood",
            },
        )
        self.assertEqual(renamed.status_code, 200, renamed.content)
        self.assertEqual(renamed.json()["name"], "Tury Wood")
        self.assertFalse(MaterialGroupBrand.objects.filter(group=coatings, name="Tury").exists())
        self.assertTrue(MaterialGroupBrand.objects.filter(group=coatings, name="Tury Wood").exists())
        self.assertEqual(Material.objects.get(group=coatings).brand, "Tury Wood")


class GoodsReceiptLineUnitDisplayTests(TestCase):
    def test_unit_display_reads_material_unit(self):
        from procurement.admin import GoodsReceiptLineInline
        from procurement.models import GoodsReceipt, GoodsReceiptLine

        org = Organization.objects.create(name="GR Org", is_supplier=True)
        wh = Warehouse.objects.create(name="GR WH", organization=org)
        material = Material.objects.create(name="Плёнка тест", unit="м")
        gr = GoodsReceipt.objects.create(warehouse=wh, supplier=org)
        line = GoodsReceiptLine.objects.create(
            goods_receipt=gr,
            material=material,
            quantity=Decimal("1"),
            unit_price=Decimal("10"),
            amount=Decimal("10"),
        )
        inline = GoodsReceiptLineInline(GoodsReceiptLine, admin.site)
        self.assertEqual(inline.unit_display(line), "м")
        self.assertIn("unit_display", GoodsReceiptLineInline.fields)
