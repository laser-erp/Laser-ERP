"""/healthz/ — проверка живости для выкладчика и внешнего мониторинга.

Отдаёт только: работает ли база, какой коммит запущен, итог последней выкладки.
Без секретов и без входа в систему.
"""

import json
import subprocess
from functools import lru_cache

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache


@lru_cache(maxsize=1)
def _running_commit() -> str:
    # Кэш на процесс: gunicorn перезапускается при каждой выкладке.
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _last_deploy():
    try:
        with open(settings.BASE_DIR / "logs" / "deploy-status.json", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return {k: data.get(k) for k in ("state", "commit", "at", "message")}


@never_cache
def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        db_ok = True
    except Exception:  # noqa: BLE001 — любая ошибка базы = нездоров
        db_ok = False
    return JsonResponse(
        {"ok": db_ok, "db": db_ok, "commit": _running_commit(), "last_deploy": _last_deploy()},
        status=200 if db_ok else 503,
    )
