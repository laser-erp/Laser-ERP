from datetime import timedelta

from django.contrib.auth import views as auth_views
from django.utils import timezone
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import TemplateView

from core.forms_password_reset import (
    LaserPasswordResetForm,
    UsernamePasswordResetRequestForm,
)
from core.models import PasswordResetRequest
from core.services.password_reset import generate_reset_short_code, is_password_reset_email_enabled


class LaserPasswordResetView(auth_views.PasswordResetView):
    template_name = "registration/admin_password_reset_form.html"
    success_url = reverse_lazy("admin_password_reset_done")
    form_class = LaserPasswordResetForm
    email_template_name = "registration/password_reset_email.html"
    subject_template_name = "registration/password_reset_subject.txt"
    extra_email_context = {"site_name": "Laser ERP"}

    def get_form_class(self):
        if is_password_reset_email_enabled():
            return LaserPasswordResetForm
        return UsernamePasswordResetRequestForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["password_reset_via_email"] = is_password_reset_email_enabled()
        return context

    def form_valid(self, form):
        if is_password_reset_email_enabled():
            return super().form_valid(form)

        user = form.resolve_user()
        if user is not None:
            req = self._recent_or_new_request(user)
            self.request.session["laser_password_reset_code"] = req.short_code
            self.request.session["laser_password_reset_username"] = user.get_username()
        else:
            # Неизвестный логин выглядит так же, как известный: иначе по ответу
            # можно перебором узнать, какие логины есть. Код никуда не сохраняется.
            self.request.session["laser_password_reset_code"] = generate_reset_short_code()
            self.request.session["laser_password_reset_username"] = form.cleaned_data.get("username", "")
        return redirect(self.get_success_url())


    MAX_REQUESTS_PER_HOUR = 3

    def _recent_or_new_request(self, user):
        """Не больше MAX_REQUESTS_PER_HOUR запросов в час на пользователя: дальше — тот же код."""
        hour_ago = timezone.now() - timedelta(hours=1)
        recent = PasswordResetRequest.objects.filter(user=user, created_at__gte=hour_ago)
        if recent.count() >= self.MAX_REQUESTS_PER_HOUR:
            return recent.order_by("-created_at").first()
        # За nginx реальный адрес клиента — в X-Real-IP.
        ip = self.request.META.get("HTTP_X_REAL_IP") or self.request.META.get("REMOTE_ADDR")
        return PasswordResetRequest.create_for_user(user, ip_address=ip)


class LaserPasswordResetDoneView(TemplateView):
    template_name = "registration/admin_password_reset_done.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["password_reset_via_email"] = is_password_reset_email_enabled()
        context["offline_code"] = self.request.session.pop("laser_password_reset_code", None)
        context["offline_username"] = self.request.session.pop("laser_password_reset_username", None)
        return context


class AccountPasswordResetView(LaserPasswordResetView):
    template_name = "registration/account_password_reset_form.html"
    success_url = reverse_lazy("account_password_reset_done")


class AccountPasswordResetDoneView(LaserPasswordResetDoneView):
    template_name = "registration/account_password_reset_done.html"
