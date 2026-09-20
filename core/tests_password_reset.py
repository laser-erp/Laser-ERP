from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import PasswordResetRequest


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ALLOWED_HOSTS=["testserver", "localhost"],
    EMAIL_HOST="smtp.test.local",
    PASSWORD_RESET_EMAIL_ENABLED=True,
)
class PasswordResetEmailFlowTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="reset_user",
            email="reset@example.com",
            password="OldPass12345!",
            is_staff=True,
        )

    def test_admin_password_reset_form_renders(self):
        response = self.client.get(reverse("admin_password_reset"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Email")

    def test_admin_password_reset_sends_email(self):
        response = self.client.post(
            reverse("admin_password_reset"),
            {"email": "reset@example.com"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("reset@example.com", mail.outbox[0].to)
        self.assertIn("/reset/", mail.outbox[0].body)

    def test_account_password_reset_sends_email(self):
        response = self.client.post(
            reverse("account_password_reset"),
            {"email": "reset@example.com"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)

    def test_unknown_email_still_redirects_without_leak(self):
        response = self.client.post(
            reverse("admin_password_reset"),
            {"email": "nobody@example.com"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)


@override_settings(
    ALLOWED_HOSTS=["testserver", "localhost"],
    PASSWORD_RESET_EMAIL_ENABLED=False,
    EMAIL_HOST="",
)
class PasswordResetOfflineFlowTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="offline_user",
            email="offline@example.com",
            password="OldPass12345!",
            is_staff=True,
        )

    def test_admin_form_shows_username_field(self):
        response = self.client.get(reverse("admin_password_reset"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Логин")
        self.assertNotContains(response, 'name="email"')

    def test_username_request_creates_code(self):
        response = self.client.post(
            reverse("admin_password_reset"),
            {"username": "offline_user"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PasswordResetRequest.objects.count(), 1)
        req = PasswordResetRequest.objects.get()
        self.assertEqual(req.user, self.user)
        self.assertEqual(len(req.short_code), 8)

        done = self.client.get(reverse("admin_password_reset_done"))
        self.assertContains(done, req.short_code)
        self.assertContains(done, "offline_user")

    def test_unknown_username_does_not_create_request(self):
        response = self.client.post(
            reverse("admin_password_reset"),
            {"username": "no_such_user"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PasswordResetRequest.objects.count(), 0)
