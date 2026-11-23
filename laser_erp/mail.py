"""Почта: решаем, можно ли сбрасывать пароль письмом.

Сами настройки SMTP (EMAIL_HOST, порт, SSL/TLS, backend) задаются в settings.py.
"""

from __future__ import annotations

import os


def configure_password_reset_email(settings: dict) -> None:
    """PASSWORD_RESET_EMAIL_ENABLED: письмом — только если SMTP настроен полностью.

    Иначе сброс идёт через администратора (короткий код). Принудительно выключить:
    PASSWORD_RESET_EMAIL_ENABLED=0.
    """
    flag = os.environ.get("PASSWORD_RESET_EMAIL_ENABLED", "").strip().lower()
    backend = str(settings.get("EMAIL_BACKEND", ""))
    smtp_ready = backend.endswith("smtp.EmailBackend") and all(
        str(settings.get(key, "") or "").strip()
        for key in ("EMAIL_HOST", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD")
    )
    if flag in ("0", "false", "no", "off"):
        settings["PASSWORD_RESET_EMAIL_ENABLED"] = False
    else:
        settings["PASSWORD_RESET_EMAIL_ENABLED"] = smtp_ready
