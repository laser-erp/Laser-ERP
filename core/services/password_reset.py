"""Password reset helpers (email or admin-assisted)."""

from __future__ import annotations

import os
import secrets
from datetime import timedelta

from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils import timezone


def is_password_reset_email_enabled() -> bool:
    """
    True when Django settings allow SMTP password reset.
    Set PASSWORD_RESET_EMAIL_ENABLED=0 in env for admin-assisted recovery (no SMTP).
    """
    from django.conf import settings

    return bool(getattr(settings, "PASSWORD_RESET_EMAIL_ENABLED", False))


def build_password_reset_path(user) -> str:
    from django.urls import reverse

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token})


def build_password_reset_url(request, user) -> str:
    return request.build_absolute_uri(build_password_reset_path(user))


def public_site_origin() -> str:
    from django.conf import settings

    domain = (
        os.environ.get("SERVER_DOMAIN", "").strip()
        or os.environ.get("DJANGO_PUBLIC_SITE_URL", "").strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    )
    if not domain:
        allowed = getattr(settings, "ALLOWED_HOSTS", None) or []
        for host in allowed:
            if host and host not in ("*", "localhost", "127.0.0.1"):
                domain = host
                break
    if not domain:
        domain = "localhost"
    use_https = getattr(settings, "USE_HTTPS", False) or os.environ.get("DJANGO_USE_HTTPS", "0") in (
        "1",
        "true",
        "True",
    )
    scheme = "https" if use_https else "http"
    return f"{scheme}://{domain}"


def build_public_site_url(path: str) -> str:
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{public_site_origin()}{path}"


def build_password_reset_public_url(user) -> str:
    """Absolute reset URL without an HTTP request (admin list, CLI)."""
    return build_public_site_url(build_password_reset_path(user))


def generate_reset_short_code() -> str:
    return secrets.token_hex(4).upper()


def password_reset_request_ttl() -> timedelta:
    hours = int(os.environ.get("PASSWORD_RESET_REQUEST_TTL_HOURS", "24"))
    return timedelta(hours=max(1, hours))
