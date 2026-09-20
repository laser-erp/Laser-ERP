#!/usr/bin/env python3
"""Apply a Yandex app password to /etc/laser-erp.env. Run on the VPS as root.

Reads the password from stdin (first line) or argv[1]. Never prints it.
Enables email password reset only if send_mail succeeds.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ENV_PATH = Path("/etc/laser-erp.env")
SMTP_USER = os.environ.get("YANDEX_SMTP_USER", "Armada.sx@yandex.ru").strip() or "Armada.sx@yandex.ru"

UPDATES = {
    "EMAIL_HOST": "smtp.yandex.ru",
    "EMAIL_PORT": "465",
    "EMAIL_USE_SSL": "1",
    "EMAIL_USE_TLS": "0",
    "EMAIL_HOST_USER": SMTP_USER,
    "DEFAULT_FROM_EMAIL": SMTP_USER,
    "SERVER_DOMAIN": "laser-erp.armada.sx",
}


def patch_env(text: str, smtp_pass: str, email_enabled: str) -> str:
    updates = dict(UPDATES)
    updates["PASSWORD_RESET_EMAIL_ENABLED"] = email_enabled
    lines = text.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            out.append(line)
            continue
        key, _ = line.split("=", 1)
        key = key.strip()
        if key == "EMAIL_HOST_PASSWORD":
            out.append(f"EMAIL_HOST_PASSWORD={smtp_pass}")
            seen.add(key)
            continue
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    if "EMAIL_HOST_PASSWORD" not in seen:
        out.append(f"EMAIL_HOST_PASSWORD={smtp_pass}")
    return "\n".join(out).rstrip() + "\n"


def send_test() -> tuple[bool, str]:
    cmd = [
        "bash",
        "-lc",
        "set -a && source /etc/laser-erp.env && set +a && "
        "cd /var/www/laser-erp && "
        "sudo -E -u lasererp .venv/bin/python manage.py shell -c "
        "\"from django.core.mail import send_mail; from django.conf import settings; "
        "n=send_mail('Laser ERP SMTP','Test OK',settings.DEFAULT_FROM_EMAIL,"
        "[settings.DEFAULT_FROM_EMAIL],fail_silently=False); print('SENT',n)\"",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    ok = proc.returncode == 0 and "SENT" in (proc.stdout or "")
    return ok, blob


def main() -> int:
    if os.geteuid() != 0:
        print("run as root", file=sys.stderr)
        return 1
    if len(sys.argv) > 1:
        raw = sys.argv[1]
    else:
        raw = sys.stdin.readline()
    smtp_pass = "".join(raw.split())
    if not smtp_pass:
        print("empty password", file=sys.stderr)
        return 2
    current = ENV_PATH.read_text(encoding="utf-8", errors="replace")
    ENV_PATH.write_text(patch_env(current, smtp_pass, "0"), encoding="utf-8")
    ENV_PATH.chmod(0o600)
    subprocess.run(["systemctl", "restart", "laser-erp"], check=True)
    ok, blob = send_test()
    redacted = blob.replace(smtp_pass, "<redacted>")
    if not ok:
        print("SMTP_TEST_FAIL")
        print(redacted[-800:])
        print("PASSWORD_RESET_EMAIL_ENABLED=0 (offline reset still works)")
        return 3
    ENV_PATH.write_text(patch_env(ENV_PATH.read_text(encoding="utf-8", errors="replace"), smtp_pass, "1"), encoding="utf-8")
    subprocess.run(["systemctl", "restart", "laser-erp"], check=True)
    print("SMTP_OK")
    print("PASSWORD_RESET_EMAIL_ENABLED=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
