from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import TemplateView

from core.forms_password_reset import (
    LaserPasswordResetForm,
    UsernamePasswordResetRequestForm,
)
from core.models import PasswordResetRequest
from core.services.password_reset import is_password_reset_email_enabled

_PASSWORD_RESET_EMAIL = {
    "email_template_name": "registration/password_reset_email.html",
    "subject_template_name": "registration/password_reset_subject.txt",
    "extra_email_context": {"site_name": "Laser ERP"},
}


class LaserPasswordResetView(auth_views.PasswordResetView):
    template_name = "registration/admin_password_reset_form.html"
    success_url = reverse_lazy("admin_password_reset_done")
    form_class = LaserPasswordResetForm
    **_PASSWORD_RESET_EMAIL

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
            req = PasswordResetRequest.create_for_user(
                user,
                ip_address=self.request.META.get("REMOTE_ADDR"),
            )
            self.request.session["laser_password_reset_code"] = req.short_code
            self.request.session["laser_password_reset_username"] = user.get_username()
        else:
            self.request.session.pop("laser_password_reset_code", None)
            self.request.session.pop("laser_password_reset_username", None)
        return redirect(self.get_success_url())


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
