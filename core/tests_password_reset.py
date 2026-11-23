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


@override_settings(
    ALLOWED_HOSTS=["testserver", "localhost"],
    PASSWORD_RESET_EMAIL_ENABLED=False,
)
class PasswordResetHardeningTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("boss", password="Pass12345!x")
        self.staff = User.objects.create_user("clerk", password="Pass12345!x", is_staff=True)
        from django.contrib.auth.models import Permission

        self.staff.user_permissions.add(*Permission.objects.filter(codename__endswith="passwordresetrequest"))
        PasswordResetRequest.create_for_user(self.admin)

    def test_staff_cannot_see_reset_links(self):
        self.client.force_login(self.staff)
        url = reverse("admin:core_passwordresetrequest_changelist")
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_superuser_sees_reset_links(self):
        self.client.force_login(self.admin)
        url = reverse("admin:core_passwordresetrequest_changelist")
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_requests_are_rate_limited(self):
        for _ in range(10):
            self.client.post(reverse("account_password_reset"), {"username": "clerk"})
        self.assertEqual(PasswordResetRequest.objects.filter(user=self.staff).count(), 3)

    def test_unknown_username_looks_the_same(self):
        known = self.client.post(reverse("account_password_reset"), {"username": "clerk"}, follow=True)
        unknown = self.client.post(reverse("account_password_reset"), {"username": "nobody"}, follow=True)
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(
            "laser_password_reset_code" in str(known.context), "laser_password_reset_code" in str(unknown.context)
        )
        self.assertTrue(known.context["offline_code"])
        self.assertTrue(unknown.context["offline_code"])
        self.assertFalse(PasswordResetRequest.objects.filter(user__username="nobody").exists())


class PasswordResetEmailFlagTests(TestCase):
    def _flag(self, **overrides):
        from laser_erp.mail import configure_password_reset_email

        settings = {
            "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "EMAIL_HOST": "smtp.yandex.ru",
            "EMAIL_HOST_USER": "u@yandex.ru",
            "EMAIL_HOST_PASSWORD": "x",
        }
        settings.update(overrides)
        configure_password_reset_email(settings)
        return settings["PASSWORD_RESET_EMAIL_ENABLED"]

    def test_full_smtp_enables_email_reset(self):
        self.assertTrue(self._flag())

    def test_missing_password_falls_back_to_admin(self):
        self.assertFalse(self._flag(EMAIL_HOST_PASSWORD=""))

    def test_dummy_backend_falls_back_to_admin(self):
        self.assertFalse(self._flag(EMAIL_BACKEND="django.core.mail.backends.dummy.EmailBackend"))
