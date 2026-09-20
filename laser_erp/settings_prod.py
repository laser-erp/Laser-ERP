"""
Production settings for Laser ERP (Ubuntu + gunicorn + nginx).

Usage:
  export DJANGO_SETTINGS_MODULE=laser_erp.settings_prod
  or EnvironmentFile=/etc/laser-erp.env in systemd (see deploy/systemd/laser-erp.service)
"""

from __future__ import annotations

import os

from .settings import *  # noqa: F403

DEBUG = os.environ.get("DJANGO_DEBUG", "0") in ("1", "true", "True", "yes", "YES")

_allowed = os.environ.get("DJANGO_ALLOWED_HOSTS", "").strip()
if _allowed:
    ALLOWED_HOSTS = [h.strip() for h in _allowed.split(",") if h.strip()]  # noqa: F405
else:
    ALLOWED_HOSTS = ["127.0.0.1", "localhost"]  # noqa: F405

_csrf = os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").strip()
if _csrf:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf.split(",") if o.strip()]

_secret = os.environ.get("DJANGO_SECRET_KEY", "").strip()
if _secret:
    SECRET_KEY = _secret  # noqa: F405
elif DEBUG:
    pass  # dev-like prod smoke test only
else:
    raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG=0")

if os.environ.get("POSTGRES_DB", "").strip():
    DATABASES = {  # noqa: F405
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ.get("POSTGRES_USER", "lasererp"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": int(os.environ.get("POSTGRES_CONN_MAX_AGE", "60")),
        }
    }
else:
    DATABASES = {  # noqa: F405
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get("SQLITE_PATH", str(BASE_DIR / "db.sqlite3")),  # noqa: F405
        }
    }

USE_HTTPS = os.environ.get("DJANGO_USE_HTTPS", "0") in ("1", "true", "True", "yes", "YES")
if USE_HTTPS:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "1") in (
        "1",
        "true",
        "True",
    )
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

_logs_dir = BASE_DIR / "logs"  # noqa: F405
_logs_dir.mkdir(exist_ok=True)

LOGGING = {  # noqa: F405
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "file": {
            "level": "ERROR",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": _logs_dir / "django_errors.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
        },
        "console": {
            "level": "ERROR",
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django.request": {
            "handlers": ["file", "console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

from laser_erp.mail import apply_email_settings  # noqa: E402

apply_email_settings(locals())
