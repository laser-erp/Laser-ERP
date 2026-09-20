"""SMTP / email backend from environment variables."""

from __future__ import annotations

import os


def _env_bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip() in ("1", "true", "True", "yes", "YES")


def apply_email_settings(settings: dict) -> None:
    """
    Configure Django email from env when EMAIL_HOST is set.
    Otherwise use console backend in DEBUG, locmem-friendly default for tests.
    """
    host = os.environ.get("EMAIL_HOST", "").strip()
    debug = settings.get("DEBUG", False)

    if host:
        settings["EMAIL_BACKEND"] = "django.core.mail.backends.smtp.EmailBackend"
        settings["EMAIL_HOST"] = host
        settings["EMAIL_PORT"] = int(os.environ.get("EMAIL_PORT", "587"))
        settings["EMAIL_HOST_USER"] = os.environ.get("EMAIL_HOST_USER", "").strip()
        settings["EMAIL_HOST_PASSWORD"] = os.environ.get("EMAIL_HOST_PASSWORD", "")
        settings["EMAIL_USE_TLS"] = _env_bool("EMAIL_USE_TLS")
        settings["EMAIL_USE_SSL"] = _env_bool("EMAIL_USE_SSL")
        default_from = os.environ.get("DEFAULT_FROM_EMAIL", "").strip()
        if not default_from:
            default_from = settings["EMAIL_HOST_USER"] or "noreply@localhost"
        settings["DEFAULT_FROM_EMAIL"] = default_from
        settings["SERVER_EMAIL"] = os.environ.get("SERVER_EMAIL", default_from).strip() or default_from
        configure_password_reset_email(settings)
        return

    if debug:
        settings["EMAIL_BACKEND"] = "django.core.mail.backends.console.EmailBackend"
    else:
        settings["EMAIL_BACKEND"] = "django.core.mail.backends.smtp.EmailBackend"

    settings.setdefault("DEFAULT_FROM_EMAIL", "noreply@laser-erp.local")
    settings.setdefault("SERVER_EMAIL", settings["DEFAULT_FROM_EMAIL"])

    configure_password_reset_email(settings)


def configure_password_reset_email(settings: dict) -> None:
    flag = os.environ.get("PASSWORD_RESET_EMAIL_ENABLED", "").strip().lower()
    host = os.environ.get("EMAIL_HOST", "").strip()
    if flag in ("0", "false", "no", "off"):
        settings["PASSWORD_RESET_EMAIL_ENABLED"] = False
    elif flag in ("1", "true", "yes", "on"):
        settings["PASSWORD_RESET_EMAIL_ENABLED"] = bool(host)
    else:
        settings["PASSWORD_RESET_EMAIL_ENABLED"] = bool(host)
