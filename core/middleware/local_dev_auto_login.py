"""Автовход без пароля только на локальном runserver (см. LOCAL_DEV_AUTO_LOGIN)."""

from django.conf import settings
from django.contrib.auth import get_user_model, login


class LocalDevAutoLoginMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, "LOCAL_DEV_AUTO_LOGIN", False):
            if self._is_local_request(request) and not getattr(request.user, "is_authenticated", False):
                user = self._pick_dev_user()
                if user is not None:
                    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return self.get_response(request)

    @staticmethod
    def _is_local_request(request) -> bool:
        addr = (request.META.get("REMOTE_ADDR") or "").strip()
        if addr in ("127.0.0.1", "::1"):
            return True
        host = (request.get_host() or "").split(":")[0].lower()
        return host in ("127.0.0.1", "localhost")

    @staticmethod
    def _pick_dev_user():
        User = get_user_model()
        username = (getattr(settings, "LOCAL_DEV_AUTO_LOGIN_USERNAME", None) or "").strip()
        if username:
            return User.objects.filter(username=username, is_active=True).first()
        user = User.objects.filter(is_superuser=True, is_active=True).order_by("pk").first()
        if user is not None:
            return user
        return User.objects.filter(is_staff=True, is_active=True).order_by("pk").first()
