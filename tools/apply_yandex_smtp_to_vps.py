#!/usr/bin/env python3
"""Apply Yandex SMTP settings to /etc/laser-erp.env on the production VPS.

Writes EMAIL_HOST_PASSWORD first with PASSWORD_RESET_EMAIL_ENABLED=0, tests
send_mail, and only then enables email password reset. Never prints secrets.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from install_vps_ssh_key import write_vps_ssh_key

SMTP_USER = os.environ.get("YANDEX_SMTP_USER", "e9650730002@yandex.ru").strip() or "e9650730002@yandex.ru"
SMTP_PASS = "".join(os.environ.get("YANDEX_SMTP_PASSWORD", "").split())
SSH_HOST = os.environ.get("VPS_HOST", "").strip()
SSH_USER = os.environ.get("VPS_USER", "root").strip() or "root"
KEY_PATH = Path.home() / ".ssh" / "vps_key"
ENV_PATH = "/etc/laser-erp.env"

BASE_UPDATES = {
    "EMAIL_HOST": "smtp.yandex.ru",
    "EMAIL_PORT": "465",
    "EMAIL_USE_SSL": "1",
    "EMAIL_USE_TLS": "0",
    "EMAIL_HOST_USER": SMTP_USER,
    "DEFAULT_FROM_EMAIL": SMTP_USER,
    "SERVER_DOMAIN": "laser-erp.armada.sx",
}

TEST_MAIL_CMD = (
    "chmod 600 /etc/laser-erp.env && "
    "systemctl restart laser-erp && "
    "set -a && source /etc/laser-erp.env && set +a && "
    "cd /var/www/laser-erp && "
    "sudo -E -u lasererp .venv/bin/python manage.py shell -c "
    "\"from django.core.mail import send_mail; from django.conf import settings; "
    "n=send_mail('Laser ERP SMTP','Test OK',settings.DEFAULT_FROM_EMAIL,"
    "[settings.DEFAULT_FROM_EMAIL],fail_silently=False); print('SENT',n)\""
)


def patch_env(text: str, updates: dict[str, str], smtp_pass: str) -> str:
    lines = text.splitlines()
    seen: set[str] = set()
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
    if smtp_pass:
        replaced = False
        final: list[str] = []
        for line in out:
            if line.startswith("EMAIL_HOST_PASSWORD="):
                final.append(f"EMAIL_HOST_PASSWORD={smtp_pass}")
                replaced = True
            else:
                final.append(line)
        if not replaced:
            final.append(f"EMAIL_HOST_PASSWORD={smtp_pass}")
        out = final
    return "\n".join(out).rstrip() + "\n"


def _redact(text: str, secret: str) -> str:
    if not secret:
        return text
    return text.replace(secret, "<redacted>")


def _exec(client: paramiko.SSHClient, cmd: str, smtp_pass: str) -> tuple[int, str, str]:
    _, stdout, stderr = client.exec_command(cmd, timeout=120)
    out = _redact(stdout.read().decode(), smtp_pass)
    err = _redact(stderr.read().decode(), smtp_pass)
    code = stdout.channel.recv_exit_status()
    return code, out, err


def _write_env(sftp: paramiko.SFTPClient, text: str) -> None:
    with sftp.open(ENV_PATH, "w") as fh:
        fh.write(text)


def main() -> int:
    if not SSH_HOST:
        print("VPS_HOST is not set", file=sys.stderr)
        return 1
    if not SMTP_PASS:
        print(
            "YANDEX_SMTP_PASSWORD is not available in this agent session. "
            "Add it to Cloud Agent secrets (same list as VPS_PASSWORD) and re-run.",
            file=sys.stderr,
        )
        return 2

    try:
        write_vps_ssh_key()
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    if not KEY_PATH.exists():
        print("Missing SSH key:", KEY_PATH, file=sys.stderr)
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        SSH_HOST,
        username=SSH_USER,
        key_filename=str(KEY_PATH),
        timeout=30,
        look_for_keys=False,
        allow_agent=False,
    )
    try:
        sftp = client.open_sftp()
        with sftp.open(ENV_PATH, "r") as fh:
            current = fh.read().decode("utf-8", errors="replace")

        disabled = dict(BASE_UPDATES)
        disabled["PASSWORD_RESET_EMAIL_ENABLED"] = "0"
        pending = patch_env(current, disabled, SMTP_PASS)
        _write_env(sftp, pending)

        code, out, err = _exec(client, TEST_MAIL_CMD, SMTP_PASS)
        if out.strip():
            print(out.strip())
        if err.strip():
            print(err.strip(), file=sys.stderr)
        if code != 0 or "SENT" not in out:
            print(
                "SMTP_TEST_FAIL; PASSWORD_RESET_EMAIL_ENABLED=0 "
                "(offline password reset still works)",
                file=sys.stderr,
            )
            return 3

        enabled = dict(BASE_UPDATES)
        enabled["PASSWORD_RESET_EMAIL_ENABLED"] = "1"
        _write_env(sftp, patch_env(pending, enabled, SMTP_PASS))
        sftp.close()
        rcode, rout, rerr = _exec(client, "chmod 600 /etc/laser-erp.env && systemctl restart laser-erp", SMTP_PASS)
        if rout.strip():
            print(rout.strip())
        if rerr.strip():
            print(rerr.strip(), file=sys.stderr)
        if rcode != 0:
            print("SMTP_OK but failed to enable email reset; flag left as written", file=sys.stderr)
            return 4
        print("SMTP_OK")
        print("PASSWORD_RESET_EMAIL_ENABLED=1")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
