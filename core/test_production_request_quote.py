from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core.models import EmailVerification, Product, ProductionRequest
from core.services.layout_path_metrics import measure_layout_file
from core.services.production_request_quote import apply_draft_quote


class LayoutPathMetricsTests(TestCase):
    def test_svg_rect_perimeter(self):
        svg = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="0" width="100" height="50" stroke="black"/>
</svg>
"""
        with NamedTemporaryFile(suffix=".svg", delete=False) as fh:
            fh.write(svg.encode("utf-8"))
            path = fh.name
        try:
            metrics = measure_layout_file(path)
            self.assertEqual(metrics.status, "ok")
            # 2*(100+50)=300 mm = 0.3 m
            self.assertEqual(metrics.cut_length_m, Decimal("0.3000"))
        finally:
            Path(path).unlink(missing_ok=True)

    def test_cdr_unsupported(self):
        with NamedTemporaryFile(suffix=".cdr", delete=False) as fh:
            fh.write(b"not-a-real-cdr")
            path = fh.name
        try:
            metrics = measure_layout_file(path)
            self.assertEqual(metrics.status, "unsupported")
        finally:
            Path(path).unlink(missing_ok=True)


class ProductionRequestOrderModeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="pr_client",
            email="pr_client@example.com",
            password="test-pass-123",
        )
        EmailVerification.objects.create(user=self.user, is_verified=True)
        self.product = Product.objects.create(name="Коробка тест", min_stock=Decimal("0"))
        self.client.force_login(self.user)

    def test_catalog_mode_creates_quote_with_personalization(self):
        response = self.client.post(
            reverse("production_request_create"),
            {
                "order_mode": "catalog",
                "customer_name": "Клиент",
                "phone": "+7000",
                "email": "pr_client@example.com",
                "request_title": "Коробка с лого",
                "quantity": "2",
                "product_id": str(self.product.pk),
                "engraving_text": "ACME",
            },
        )
        self.assertEqual(response.status_code, 302)
        req = ProductionRequest.objects.get(request_title="Коробка с лого")
        self.assertEqual(req.order_mode, ProductionRequest.ORDER_MODE_CATALOG)
        self.assertEqual(req.engraving_text, "ACME")
        self.assertIsNotNone(req.draft_total_cost)
        # 0 себестоимость + 250 персонализация × 2
        self.assertEqual(req.draft_total_cost, Decimal("500.00"))

    def test_custom_mode_requires_dxf(self):
        response = self.client.post(
            reverse("production_request_create"),
            {
                "order_mode": "custom",
                "customer_name": "Клиент",
                "phone": "+7000",
                "email": "pr_client@example.com",
                "request_title": "Свой макет",
                "quantity": "1",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "DXF или SVG")

    def test_custom_mode_svg_sets_cut_length(self):
        svg = b"""<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg">
  <line x1="0" y1="0" x2="1000" y2="0" stroke="black"/>
</svg>
"""
        upload = SimpleUploadedFile("part.svg", svg, content_type="image/svg+xml")
        response = self.client.post(
            reverse("production_request_create"),
            {
                "order_mode": "custom",
                "customer_name": "Клиент",
                "phone": "+7000",
                "email": "pr_client@example.com",
                "request_title": "Рез по SVG",
                "quantity": "1",
                "layout_file": upload,
            },
        )
        self.assertEqual(response.status_code, 302)
        req = ProductionRequest.objects.get(request_title="Рез по SVG")
        self.assertEqual(req.layout_metrics_status, ProductionRequest.METRICS_OK)
        self.assertEqual(req.layout_cut_length_m, Decimal("1.0000"))
        self.assertGreater(req.draft_total_cost, Decimal("0"))
