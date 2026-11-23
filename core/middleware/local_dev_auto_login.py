"""Автовход без пароля только на локальном runserver (см. LOCAL_DEV_AUTO_LOGIN)."""

from django.conf import settings
from django.contrib.auth import get_user_model, login


class LocalDevAutoLoginMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Двойная защита: даже если LOCAL_DEV_AUTO_LOGIN случайно включён на сервере,
        # без DEBUG (а он выключен в settings_prod и в тестах) автовход не сработает.
        if settings.DEBUG and getattr(settings, "LOCAL_DEV_AUTO_LOGIN", False):
            if self._is_local_request(request) and not getattr(request.user, "is_authenticated", False):
                user = self._pick_dev_user()
                if user is not None:
                    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return self.get_response(request)

    @staticmethod
    def _is_local_request(request) -> bool:
        # Только прямое обращение к runserver с этой же машины.
        # Запросы через nginx тоже приходят с 127.0.0.1, но несут X-Forwarded-For / X-Real-IP —
        # такие не пускаем. Заголовку Host не доверяем: его задаёт клиент.
        if request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("HTTP_X_REAL_IP"):
            return False
        addr = (request.META.get("REMOTE_ADDR") or "").strip()
        return addr in ("127.0.0.1", "::1")

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
