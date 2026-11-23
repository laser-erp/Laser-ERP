from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.middleware.local_dev_auto_login import LocalDevAutoLoginMiddleware
from core.models import Order

User = get_user_model()


class OrderSuccessAccessTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password="Pass12345!")
        self.other = User.objects.create_user("other", password="Pass12345!")
        self.order = Order.objects.create(
            customer_name="Клиент",
            comment=f"phone=1; email=c@example.com; user_id={self.owner.pk}; username=owner",
        )
        self.url = reverse("order_success", args=[self.order.pk])

    def test_anonymous_without_session_gets_404(self):
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_other_user_gets_404(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_owner_can_view(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_checkout_session_can_view(self):
        session = self.client.session
        session["checkout_summary"] = {"order_id": self.order.pk}
        session.save()
        self.assertEqual(self.client.get(self.url).status_code, 200)


class OrderOwnerMarkerTests(TestCase):
    def test_user_1_does_not_see_user_12_orders(self):
        users = [User.objects.create_user(f"u{i}") for i in range(12)]
        u_short, u_long = users[0], users[11]
        # подгоняем pk так, чтобы один был префиксом другого (например 1 и 12)
        if not str(u_long.pk).startswith(str(u_short.pk)):
            u_long = User.objects.create_user("u_prefix", pk=int(f"{u_short.pk}2"))
        order = Order.objects.create(customer_name="X", comment=f"user_id={u_long.pk}; username=x")
        self.client.force_login(u_short)
        response = self.client.get(reverse("account_order_detail", args=[order.pk]))
        self.assertIn(response.status_code, (302, 404))
        self.assertNotEqual(response.status_code, 200)


class LocalDevAutoLoginTests(TestCase):
    def setUp(self):
        User.objects.create_superuser("root_admin", password="Pass12345!")
        self.factory = RequestFactory()

    def _run(self, **meta):
        from django.contrib.auth.models import AnonymousUser
        from django.contrib.sessions.backends.db import SessionStore

        request = self.factory.get("/", **meta)
        request.user = AnonymousUser()
        request.session = SessionStore()
        LocalDevAutoLoginMiddleware(lambda r: None)(request)
        return request.user.is_authenticated

    @override_settings(DEBUG=True, LOCAL_DEV_AUTO_LOGIN=True)
    def test_direct_local_request_logs_in(self):
        self.assertTrue(self._run(REMOTE_ADDR="127.0.0.1"))

    @override_settings(DEBUG=True, LOCAL_DEV_AUTO_LOGIN=True)
    def test_request_via_nginx_is_not_logged_in(self):
        self.assertFalse(self._run(REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="8.8.8.8"))

    @override_settings(DEBUG=True, LOCAL_DEV_AUTO_LOGIN=True, ALLOWED_HOSTS=["*"])
    def test_spoofed_host_is_not_logged_in(self):
        self.assertFalse(self._run(REMOTE_ADDR="8.8.8.8", HTTP_HOST="localhost"))

    @override_settings(DEBUG=False, LOCAL_DEV_AUTO_LOGIN=True)
    def test_disabled_without_debug(self):
        self.assertFalse(self._run(REMOTE_ADDR="127.0.0.1"))


class HealthzTests(TestCase):
    def test_healthz_is_public_and_reports_db(self):
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertIn("commit", data)
        self.assertNotIn("SECRET", response.content.decode().upper())
