from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ALLOWED_HOSTS=["testserver", "localhost"],
)
class PasswordResetFlowTests(TestCase):
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
