#!/usr/bin/env python3
"""Apply Yandex SMTP settings to /etc/laser-erp.env on the production VPS."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import paramiko

SMTP_USER = os.environ.get("YANDEX_SMTP_USER", "Armada.sx@yandex.ru").strip()
SMTP_PASS = os.environ.get("YANDEX_SMTP_PASSWORD", "").strip()
SSH_HOST = os.environ.get("VPS_HOST", "").strip()
SSH_USER = os.environ.get("VPS_USER", "root")
KEY_PATH = Path.home() / ".ssh" / "laser_erp_agent"

UPDATES = {
    "PASSWORD_RESET_EMAIL_ENABLED": "1",
    "EMAIL_HOST": "smtp.yandex.ru",
    "EMAIL_PORT": "465",
    "EMAIL_USE_SSL": "1",
    "EMAIL_USE_TLS": "0",
    "EMAIL_HOST_USER": SMTP_USER,
    "DEFAULT_FROM_EMAIL": SMTP_USER,
    "SERVER_DOMAIN": "laser-erp.armada.sx",
}


def patch_env(text: str, updates: dict[str, str]) -> str:
    lines = text.splitlines()
    seen = set()
    out: list[str] = []
    for line in lines:
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            out.append(line)
            continue
        key, _ = line.split("=", 1)
        key = key.strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    if SMTP_PASS:
        replaced = False
        final: list[str] = []
        for line in out:
            if line.startswith("EMAIL_HOST_PASSWORD="):
                final.append(f"EMAIL_HOST_PASSWORD={SMTP_PASS}")
                replaced = True
            else:
                final.append(line)
        if not replaced:
            final.append(f"EMAIL_HOST_PASSWORD={SMTP_PASS}")
        out = final
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    if not SSH_HOST:
        print("VPS_HOST is not set", file=sys.stderr)
        return 1
    if not KEY_PATH.exists():
        print("Missing SSH key:", KEY_PATH, file=sys.stderr)
        return 1
    if not SMTP_PASS:
        print(
            "YANDEX_SMTP_PASSWORD is not available in this agent session. "
            "Add it to Cloud Agent secrets (same list as VPS_PASSWORD) and re-run.",
            file=sys.stderr,
        )
        return 2

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        SSH_HOST,
        username=SSH_USER,
        key_filename=str(KEY_PATH),
        timeout=30,
    )
    try:
        sftp = client.open_sftp()
        with sftp.open("/etc/laser-erp.env", "r") as fh:
            current = fh.read().decode("utf-8", errors="replace")
        new_text = patch_env(current, UPDATES)
        with sftp.open("/etc/laser-erp.env", "w") as fh:
            fh.write(new_text)
        sftp.close()

        cmd = (
            "systemctl restart laser-erp && "
            "set -a && source /etc/laser-erp.env && set +a && "
            "cd /var/www/laser-erp && "
            "sudo -E -u lasererp .venv/bin/python manage.py shell -c "
            "\"from django.core.mail import send_mail; from django.conf import settings; "
            "n=send_mail('Laser ERP SMTP','Test OK',settings.DEFAULT_FROM_EMAIL,"
            f"[settings.DEFAULT_FROM_EMAIL],fail_silently=False); print('SENT',n)\""
        )
        _, stdout, stderr = client.exec_command(cmd, timeout=120)
        out = stdout.read().decode()
        err = stderr.read().decode()
        code = stdout.channel.recv_exit_status()
        print(out.strip())
        if err.strip():
            print(err.strip(), file=sys.stderr)
        return 0 if code == 0 and "SENT" in out else 3
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
