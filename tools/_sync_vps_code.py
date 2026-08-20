#!/usr/bin/env python3
"""Incremental VPS sync: upload changed project files, migrate, collectstatic, restart.

Does NOT wipe APP_DIR and does NOT loaddata (unlike tools/_deploy_server.py).
"""
from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

import paramiko

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.server"

SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".cursor",
    "бекапы",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "media",
    "logs",
    "staticfiles",
    "tools/_deploy_tmp",
}
SKIP_FILES = {
    "db.sqlite3",
    "debug.log",
    ".env",
    ".env.server",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".sqlite3", ".zip", ".log"}


def read_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def should_skip(rel: Path) -> bool:
    if any(part in SKIP_DIRS for part in rel.parts):
        return True
    if rel.name in SKIP_FILES:
        return True
    if rel.suffix.lower() in SKIP_SUFFIXES:
        return True
    return False


def iter_project_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dp = Path(dirpath)
        rel_dir = dp.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel_dir.parts):
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            fp = dp / name
            rel = fp.relative_to(ROOT)
            if should_skip(rel):
                continue
            yield fp, rel.as_posix()


def ssh_exec(ssh: paramiko.SSHClient, cmd: str, check: bool = True) -> str:
    print(f"REMOTE: {cmd}")
    _stdin, stdout, stderr = ssh.exec_command(cmd, timeout=600)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out)
    if err.strip():
        print(err, file=sys.stderr)
    if check and code != 0:
        raise RuntimeError(f"Remote command failed ({code}): {cmd}")
    return out


def ensure_remote_dir(sftp: paramiko.SFTPClient, remote_dir: str) -> None:
    parts = remote_dir.strip("/").split("/")
    cur = ""
    for part in parts:
        cur += "/" + part
        try:
            sftp.stat(cur)
        except OSError:
            sftp.mkdir(cur)


def main() -> None:
    if not ENV_FILE.exists():
        raise RuntimeError(f"Missing {ENV_FILE}")
    env = read_env(ENV_FILE)
    server_ip = env["SERVER_IP"]
    ssh_user = env.get("SSH_USER", "root")
    ssh_port = int(env.get("SSH_PORT", "22"))
    ssh_password = env.get("SSH_PASSWORD", "")
    app_user = env.get("APP_USER", "lasererp")
    app_dir = env.get("APP_DIR", "/var/www/laser-erp")
    if not ssh_password:
        raise RuntimeError("SSH_PASSWORD is empty in .env.server")

    files = list(iter_project_files())
    print(f"Uploading {len(files)} files to {app_dir} ...")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(server_ip, port=ssh_port, username=ssh_user, password=ssh_password, timeout=30)
    sftp = ssh.open_sftp()
    try:
        for local, rel in files:
            remote = f"{app_dir.rstrip('/')}/{rel}"
            ensure_remote_dir(sftp, str(Path(remote).parent).replace("\\", "/"))
            sftp.put(str(local), remote)

        ssh_exec(ssh, f"chown -R {shlex.quote(app_user)}:www-data {shlex.quote(app_dir)}")

        # Prefer explicit Postgres env from /etc/laser-erp.env (Ubuntu sudo -E drops vars).
        migrate_cmd = (
            f"set -a; source /etc/laser-erp.env; set +a; "
            f"cd {shlex.quote(app_dir)}; "
            f"sudo -u {shlex.quote(app_user)} env "
            f"DJANGO_SETTINGS_MODULE=\"$DJANGO_SETTINGS_MODULE\" "
            f"DJANGO_SECRET_KEY=\"$DJANGO_SECRET_KEY\" "
            f"DJANGO_ALLOWED_HOSTS=\"$DJANGO_ALLOWED_HOSTS\" "
            f"DJANGO_DEBUG=\"${{DJANGO_DEBUG:-0}}\" "
            f"DJANGO_USE_HTTPS=\"${{DJANGO_USE_HTTPS:-1}}\" "
            f"POSTGRES_DB=\"$POSTGRES_DB\" "
            f"POSTGRES_USER=\"$POSTGRES_USER\" "
            f"POSTGRES_PASSWORD=\"$POSTGRES_PASSWORD\" "
            f"POSTGRES_HOST=\"${{POSTGRES_HOST:-127.0.0.1}}\" "
            f"POSTGRES_PORT=\"${{POSTGRES_PORT:-5432}}\" "
            f".venv/bin/python manage.py {{action}}"
        )
        ssh_exec(ssh, f"/bin/bash -lc {shlex.quote(migrate_cmd.format(action='check'))}")
        ssh_exec(ssh, f"/bin/bash -lc {shlex.quote(migrate_cmd.format(action='migrate --noinput'))}")
        ssh_exec(ssh, f"/bin/bash -lc {shlex.quote(migrate_cmd.format(action='collectstatic --noinput'))}")
        ssh_exec(ssh, "systemctl restart laser-erp")
        ssh_exec(ssh, "systemctl --no-pager --full status laser-erp | sed -n '1,20p'", check=False)
        print("SYNC OK")
    finally:
        sftp.close()
        ssh.close()


if __name__ == "__main__":
    main()
