#!/usr/bin/env python3
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
ENV_FILE = ROOT / ".env.server"


def read_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


REMOTE_PY = r'''
import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.environ.get("DJANGO_SETTINGS_MODULE", "laser_erp.settings_prod"))
django.setup()
from django.conf import settings
from core.models import AdminInvite

print("EMAIL_BACKEND=", getattr(settings, "EMAIL_BACKEND", None))
print("EMAIL_HOST=", getattr(settings, "EMAIL_HOST", None) or "(empty)")
print("EMAIL_PORT=", getattr(settings, "EMAIL_PORT", None))
print("EMAIL_HOST_USER=", getattr(settings, "EMAIL_HOST_USER", None) or "(empty)")
print("DEFAULT_FROM_EMAIL=", getattr(settings, "DEFAULT_FROM_EMAIL", None))
print("EMAIL_USE_TLS=", getattr(settings, "EMAIL_USE_TLS", None))
print("--- invites ---")
qs = AdminInvite.objects.order_by("-id")[:10]
if not qs:
    print("(no invites)")
for inv in qs:
    print(
        f"id={inv.id} email={inv.email} role={inv.role} "
        f"created={inv.created_at} sent={inv.sent_at} accepted={inv.accepted_at}"
    )
    print(f"accept_url=https://laser-erp.armada.sx/account/invite/{inv.token}/")
'''


def main() -> None:
    env = read_env(ENV_FILE)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        env["SERVER_IP"],
        port=int(env.get("SSH_PORT", "22")),
        username=env.get("SSH_USER", "root"),
        password=env.get("SSH_PASSWORD", ""),
        timeout=20,
    )
    remote_path = "/tmp/_check_admin_invites.py"
    sftp = ssh.open_sftp()
    try:
        with sftp.file(remote_path, "w") as f:
            f.write(REMOTE_PY)
        cmd = (
            "/bin/bash -lc 'set -a; source /etc/laser-erp.env; set +a; "
            "cd /var/www/laser-erp; sudo -u lasererp env "
            'DJANGO_SETTINGS_MODULE="$DJANGO_SETTINGS_MODULE" '
            'DJANGO_SECRET_KEY="$DJANGO_SECRET_KEY" '
            'DJANGO_ALLOWED_HOSTS="$DJANGO_ALLOWED_HOSTS" '
            'DJANGO_DEBUG="${DJANGO_DEBUG:-0}" '
            'DJANGO_USE_HTTPS="${DJANGO_USE_HTTPS:-1}" '
            'POSTGRES_DB="$POSTGRES_DB" '
            'POSTGRES_USER="$POSTGRES_USER" '
            'POSTGRES_PASSWORD="$POSTGRES_PASSWORD" '
            'POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}" '
            'POSTGRES_PORT="${POSTGRES_PORT:-5432}" '
            'EMAIL_HOST="${EMAIL_HOST:-}" '
            'EMAIL_PORT="${EMAIL_PORT:-}" '
            'EMAIL_HOST_USER="${EMAIL_HOST_USER:-}" '
            'EMAIL_HOST_PASSWORD="${EMAIL_HOST_PASSWORD:-}" '
            'EMAIL_USE_TLS="${EMAIL_USE_TLS:-}" '
            'DEFAULT_FROM_EMAIL="${DEFAULT_FROM_EMAIL:-}" '
            "PYTHONPATH=/var/www/laser-erp "
            f".venv/bin/python {remote_path}'"
        )
        print(f"REMOTE: check invites")
        _stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        print(out)
        if err.strip():
            print(err, file=sys.stderr)
        if code != 0:
            raise SystemExit(code)
    finally:
        try:
            sftp.remove(remote_path)
        except OSError:
            pass
        sftp.close()
        ssh.close()


if __name__ == "__main__":
    main()
