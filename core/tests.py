from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import (
    AssignmentMaterialReservation,
    Material,
    MaterialBatch,
    MaterialReservation,
    MaterialStock,
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
