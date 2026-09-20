#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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


REMOTE_PY = r"""
import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.environ.get("DJANGO_SETTINGS_MODULE", "laser_erp.settings_prod"))
django.setup()
from core.models import AdminInvite
updated = AdminInvite.objects.filter(accepted_at__isnull=True).exclude(sent_at__isnull=True).update(sent_at=None)
print(f"cleared_sent_at={updated}")
for inv in AdminInvite.objects.order_by("-id")[:5]:
    print(f"id={inv.id} email={inv.email} sent={inv.sent_at} accepted={inv.accepted_at}")
"""


def main() -> None:
    env = read_env(ROOT / ".env.server")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        env["SERVER_IP"],
        port=int(env.get("SSH_PORT", "22")),
        username=env.get("SSH_USER", "root"),
        password=env.get("SSH_PASSWORD", ""),
        timeout=20,
    )
    remote = "/tmp/_clear_fake_invite_sent.py"
    sftp = ssh.open_sftp()
    try:
        with sftp.file(remote, "w") as f:
            f.write(REMOTE_PY)
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
            "PYTHONPATH=/var/www/laser-erp "
            f".venv/bin/python {remote}'"
        )
        _stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
        print(stdout.read().decode("utf-8", errors="replace"))
        err = stderr.read().decode("utf-8", errors="replace")
        if err.strip():
            print(err, file=sys.stderr)
    finally:
        try:
            sftp.remove(remote)
        except OSError:
            pass
        sftp.close()
        ssh.close()


if __name__ == "__main__":
    main()
