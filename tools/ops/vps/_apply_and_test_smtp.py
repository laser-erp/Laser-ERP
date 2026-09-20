#!/usr/bin/env python3
"""Apply SMTP env on VPS, test send_mail, resend pending AdminInvite."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_TOOLS = Path(__file__).resolve().parents[2]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
from project_root import PROJECT_ROOT as ROOT


def read_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


REMOTE_TEST = r'''
import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.environ.get("DJANGO_SETTINGS_MODULE", "laser_erp.settings_prod"))
django.setup()
from django.conf import settings
from django.core.mail import send_mail
from core.models import AdminInvite
from django.utils import timezone

print("EMAIL_BACKEND=", settings.EMAIL_BACKEND)
print("EMAIL_HOST=", settings.EMAIL_HOST)
print("EMAIL_PORT=", settings.EMAIL_PORT)
print("EMAIL_USE_SSL=", getattr(settings, "EMAIL_USE_SSL", None))
print("EMAIL_USE_TLS=", getattr(settings, "EMAIL_USE_TLS", None))
print("EMAIL_HOST_USER=", settings.EMAIL_HOST_USER)
print("DEFAULT_FROM_EMAIL=", settings.DEFAULT_FROM_EMAIL)
print("PASSWORD_SET=", bool(settings.EMAIL_HOST_PASSWORD))

# Self-test to the same mailbox (or first pending invite email)
invite = AdminInvite.objects.filter(accepted_at__isnull=True).order_by("-id").first()
to_addr = invite.email if invite else settings.EMAIL_HOST_USER
print("TEST_TO=", to_addr)
send_mail(
    "Laser ERP: тест SMTP",
    "Это тестовое письмо. Если вы его видите — SMTP настроен верно.",
    settings.DEFAULT_FROM_EMAIL,
    [to_addr],
    fail_silently=False,
)
print("TEST_SEND_OK")

if invite:
    from django.urls import reverse
    from django.test import RequestFactory
    # Build absolute URL without request
    accept_url = f"https://laser-erp.armada.sx/account/invite/{invite.token}/"
    send_mail(
        "Приглашение в админку Laser ERP",
        (
            "Здравствуйте!\n\n"
            "Вам отправлено приглашение для доступа в админку Laser ERP.\n\n"
            f"Перейдите по ссылке, чтобы подтвердить email и задать пароль:\n{accept_url}\n\n"
            "Если это были не вы — просто проигнорируйте письмо."
        ),
        settings.DEFAULT_FROM_EMAIL,
        [invite.email],
        fail_silently=False,
    )
    invite.sent_at = timezone.now()
    invite.save(update_fields=["sent_at"])
    print(f"INVITE_RESENT id={invite.id} email={invite.email} url={accept_url}")
else:
    print("NO_PENDING_INVITE")
'''


def upsert_env_text(text: str, updates: dict[str, str]) -> str:
    email_keys = list(updates.keys())
    lines = text.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        raw = line.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            key = raw.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)
    missing = [k for k in email_keys if k not in seen]
    if missing:
        if out and out[-1].strip():
            out.append("")
        out.append("# --- SMTP Laser ERP ---")
        for key in missing:
            out.append(f"{key}={updates[key]}")
    return "\n".join(out) + "\n"


def main() -> None:
    env = read_env(ROOT / ".env.server")
    keys = (
        "EMAIL_HOST",
        "EMAIL_PORT",
        "EMAIL_USE_SSL",
        "EMAIL_USE_TLS",
        "EMAIL_HOST_USER",
        "EMAIL_HOST_PASSWORD",
        "DEFAULT_FROM_EMAIL",
    )
    updates = {k: env.get(k, "") for k in keys}
    if not updates["EMAIL_HOST_PASSWORD"]:
        raise SystemExit("EMAIL_HOST_PASSWORD empty")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        env["SERVER_IP"],
        port=int(env.get("SSH_PORT", "22")),
        username=env.get("SSH_USER", "root"),
        password=env.get("SSH_PASSWORD", ""),
        timeout=20,
    )
    sftp = ssh.open_sftp()
    remote_env = "/etc/laser-erp.env"
    remote_py = "/tmp/_test_smtp_invite.py"
    try:
        with sftp.file(remote_env, "r") as f:
            current = f.read().decode("utf-8", errors="replace")
        ssh.exec_command(f"cp {remote_env} {remote_env}.bak.email")
        with sftp.file(remote_env, "w") as f:
            f.write(upsert_env_text(current, updates))
        print("ENV_UPDATED")

        for cmd in (
            "systemctl restart laser-erp",
            "sleep 2",
            "systemctl is-active laser-erp",
        ):
            print("REMOTE:", cmd)
            _stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
            print(stdout.read().decode("utf-8", errors="replace").strip())
            err = stderr.read().decode("utf-8", errors="replace").strip()
            if err:
                print(err, file=sys.stderr)

        with sftp.file(remote_py, "w") as f:
            f.write(REMOTE_TEST)

        cmd = (
            "/bin/bash -lc 'set -a; source /etc/laser-erp.env; set +a; "
            "cd /var/www/laser-erp; sudo -u lasererp env "
            'DJANGO_SETTINGS_MODULE="$DJANGO_SETTINGS_MODULE" '
            'DJANGO_SECRET_KEY="$DJANGO_SECRET_KEY" '
            'DJANGO_ALLOWED_HOSTS="$DJANGO_ALLOWED_HOSTS" '
            'DJANGO_DEBUG="${DJANGO_DEBUG:-0}" '
            'DJANGO_USE_HTTPS="${DJANGO_USE_HTTPS:-1}" '
            'POSTGRES_DB="$POSTGRES_DB" POSTGRES_USER="$POSTGRES_USER" '
            'POSTGRES_PASSWORD="$POSTGRES_PASSWORD" '
            'POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}" '
            'POSTGRES_PORT="${POSTGRES_PORT:-5432}" '
            'EMAIL_HOST="$EMAIL_HOST" EMAIL_PORT="$EMAIL_PORT" '
            'EMAIL_USE_SSL="$EMAIL_USE_SSL" EMAIL_USE_TLS="$EMAIL_USE_TLS" '
            'EMAIL_HOST_USER="$EMAIL_HOST_USER" '
            'EMAIL_HOST_PASSWORD="$EMAIL_HOST_PASSWORD" '
            'DEFAULT_FROM_EMAIL="$DEFAULT_FROM_EMAIL" '
            "PYTHONPATH=/var/www/laser-erp "
            f".venv/bin/python {remote_py}'"
        )
        print("REMOTE: smtp test + resend invite")
        _stdin, stdout, stderr = ssh.exec_command(cmd, timeout=90)
        print(stdout.read().decode("utf-8", errors="replace"))
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        if err.strip():
            print(err, file=sys.stderr)
        if code != 0:
            raise SystemExit(code)
        print("DONE")
    finally:
        try:
            sftp.remove(remote_py)
        except OSError:
            pass
        sftp.close()
        ssh.close()


if __name__ == "__main__":
    main()
