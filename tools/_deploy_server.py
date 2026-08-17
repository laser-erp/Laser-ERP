#!/usr/bin/env python3
from __future__ import annotations

import fnmatch
import os
import shlex
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import paramiko

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.server"
TMP_DIR = ROOT / "tools" / "_deploy_tmp"
CODE_ZIP = TMP_DIR / "code.zip"
MEDIA_ZIP = TMP_DIR / "media.zip"

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
}
SKIP_FILES = {
    "db.sqlite3",
    "debug.log",
}
SKIP_GLOBS = {"*.pyc", "*.pyo", "*.sqlite3", "*.zip", "*.log"}


def read_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def create_zip(src: Path, dst: Path, include_media: bool = False) -> None:
    if dst.exists():
        dst.unlink()
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(src):
            dp = Path(dirpath)
            rel = dp.relative_to(src)
            if any(part in SKIP_DIRS for part in rel.parts):
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS or (include_media and d == "media")]
            for name in filenames:
                fp = dp / name
                rel_file = fp.relative_to(src)
                if not include_media and "media" in rel_file.parts:
                    continue
                if include_media and (not rel_file.parts or rel_file.parts[0] != "media"):
                    continue
                if name in SKIP_FILES:
                    continue
                if any(fnmatch.fnmatch(name, pat) for pat in SKIP_GLOBS):
                    continue
                zf.write(fp, rel_file.as_posix())


def run_local(cmd: list[str]) -> None:
    print("LOCAL:", " ".join(shlex.quote(c) for c in cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)


def ssh_exec(ssh: paramiko.SSHClient, cmd: str, env: dict[str, str] | None = None, check: bool = True) -> str:
    prefix = ""
    if env:
        prefix = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items()) + " "
    full = prefix + cmd
    print("REMOTE:", full)
    stdin, stdout, stderr = ssh.exec_command(full, get_pty=True)
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


def bash_wrap(cmd: str) -> str:
    return f"/bin/bash -lc {shlex.quote(cmd)}"


def sftp_put(sftp: paramiko.SFTPClient, local: Path, remote: str) -> None:
    print(f"UPLOAD: {local} -> {remote}")
    sftp.put(str(local), remote)


def main() -> None:
    env = read_env(ENV_FILE)
    server_ip = env["SERVER_IP"]
    server_domain = env.get("SERVER_DOMAIN", "").strip()
    ssh_user = env.get("SSH_USER", "root")
    ssh_port = int(env.get("SSH_PORT", "22"))
    ssh_password = env.get("SSH_PASSWORD", "")
    app_user = env.get("APP_USER", "lasererp")
    app_dir = env.get("APP_DIR", "/var/www/laser-erp")

    if not ssh_password:
        raise RuntimeError("SSH_PASSWORD is empty in .env.server")

    TMP_DIR.mkdir(parents=True, exist_ok=True)

    export_name = f"data_export_{__import__('datetime').date.today().isoformat()}.json"
    export_file = ROOT / "бекапы" / export_name
    run_local([str(ROOT / ".venv" / "Scripts" / "python.exe"), "tools/export_data.py"])
    create_zip(ROOT, CODE_ZIP, include_media=False)
    media_dir = ROOT / "media"
    has_media = media_dir.is_dir() and any(media_dir.iterdir())
    if has_media:
        create_zip(ROOT, MEDIA_ZIP, include_media=True)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(server_ip, port=ssh_port, username=ssh_user, password=ssh_password, timeout=20)
    sftp = ssh.open_sftp()

    try:
        ssh_exec(ssh, "uname -a && lsb_release -a || cat /etc/os-release")
        ssh_exec(
            ssh,
            "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y "
            "python3 python3-venv python3-pip git nginx postgresql postgresql-contrib",
        )
        ssh_exec(
            ssh,
            f"id {shlex.quote(app_user)} >/dev/null 2>&1 || adduser --disabled-password --gecos '' {shlex.quote(app_user)}",
        )
        ssh_exec(ssh, f"usermod -aG www-data {shlex.quote(app_user)} || true")
        ssh_exec(ssh, f"mkdir -p {shlex.quote(app_dir)} /var/backups/laser-erp /etc/nginx/sites-available /etc/nginx/sites-enabled")
        ssh_exec(ssh, f"rm -rf {shlex.quote(app_dir)}/*")

        sftp_put(sftp, CODE_ZIP, "/root/laser-erp-code.zip")
        sftp_put(sftp, export_file, f"{app_dir}/{export_name}")
        if has_media:
            sftp_put(sftp, MEDIA_ZIP, "/root/laser-erp-media.zip")

        ssh_exec(ssh, f"python3 -m zipfile -e /root/laser-erp-code.zip {shlex.quote(app_dir)}")
        if has_media:
            ssh_exec(ssh, f"python3 -m zipfile -e /root/laser-erp-media.zip {shlex.quote(app_dir)}")
        ssh_exec(ssh, f"mkdir -p {shlex.quote(app_dir)}/logs {shlex.quote(app_dir)}/staticfiles {shlex.quote(app_dir)}/media")
        ssh_exec(ssh, f"chown -R {shlex.quote(app_user)}:www-data {shlex.quote(app_dir)} /var/backups/laser-erp")

        postgres_password = env["POSTGRES_PASSWORD"]
        postgres_db = env["POSTGRES_DB"]
        postgres_user = env["POSTGRES_USER"]
        ssh_exec(
            ssh,
            f"sudo -u postgres psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='{postgres_user}'\" | grep -q 1 "
            f"|| sudo -u postgres psql -c \"CREATE USER {postgres_user} WITH PASSWORD '{postgres_password}';\"",
        )
        ssh_exec(
            ssh,
            f"sudo -u postgres psql -tc \"SELECT 1 FROM pg_database WHERE datname='{postgres_db}'\" | grep -q 1 "
            f"|| sudo -u postgres psql -c \"CREATE DATABASE {postgres_db} OWNER {postgres_user};\"",
        )

        allowed_hosts = env.get("DJANGO_ALLOWED_HOSTS", "").strip() or ",".join(
            part for part in [server_domain, server_ip] if part
        )
        env_text = "\n".join(
            [
                "DJANGO_SETTINGS_MODULE=laser_erp.settings_prod",
                "DJANGO_DEBUG=0",
                f"DJANGO_SECRET_KEY={env['DJANGO_SECRET_KEY']}",
                f"DJANGO_ALLOWED_HOSTS={allowed_hosts}",
                "DJANGO_USE_HTTPS=0",
                f"POSTGRES_DB={postgres_db}",
                f"POSTGRES_USER={postgres_user}",
                f"POSTGRES_PASSWORD={postgres_password}",
                "POSTGRES_HOST=127.0.0.1",
                "POSTGRES_PORT=5432",
                f"FNS_API_KEY={env.get('FNS_API_KEY', '')}",
                "UPLOAD_MAX_SIZE_MB=20",
                "",
            ]
        )
        with sftp.file("/etc/laser-erp.env", "w") as f:
            f.write(env_text)
        ssh_exec(ssh, "chmod 600 /etc/laser-erp.env")

        ssh_exec(ssh, f"cd {shlex.quote(app_dir)} && sudo -u {shlex.quote(app_user)} python3 -m venv .venv")
        ssh_exec(ssh, f"cd {shlex.quote(app_dir)} && sudo -u {shlex.quote(app_user)} .venv/bin/pip install --upgrade pip")
        ssh_exec(ssh, f"cd {shlex.quote(app_dir)} && sudo -u {shlex.quote(app_user)} .venv/bin/pip install -r requirements.txt")

        base_env = f"set -a; source /etc/laser-erp.env; set +a; cd {shlex.quote(app_dir)}; "
        ssh_exec(ssh, bash_wrap(base_env + f"sudo -E -u {shlex.quote(app_user)} .venv/bin/python manage.py migrate --noinput"))
        ssh_exec(ssh, bash_wrap(base_env + f"sudo -E -u {shlex.quote(app_user)} .venv/bin/python manage.py loaddata {shlex.quote(export_name)}"))
        ssh_exec(ssh, bash_wrap(base_env + f"sudo -E -u {shlex.quote(app_user)} .venv/bin/python manage.py collectstatic --noinput"))
        ssh_exec(ssh, bash_wrap(base_env + f"sudo -E -u {shlex.quote(app_user)} .venv/bin/python manage.py check --deploy"), check=False)

        nginx_conf = f"{app_dir}/deploy/nginx/laser-erp.conf"
        systemd_service = f"{app_dir}/deploy/systemd/laser-erp.service"
        cron_file = f"{app_dir}/deploy/cron/laser-erp-backup"
        ssh_exec(ssh, f"cp {shlex.quote(systemd_service)} /etc/systemd/system/laser-erp.service")
        ssh_exec(ssh, f"cp {shlex.quote(nginx_conf)} /etc/nginx/sites-available/laser-erp")
        ssh_exec(ssh, "ln -sf /etc/nginx/sites-available/laser-erp /etc/nginx/sites-enabled/laser-erp && rm -f /etc/nginx/sites-enabled/default")
        ssh_exec(ssh, f"cp {shlex.quote(cron_file)} /etc/cron.d/laser-erp-backup && chmod 644 /etc/cron.d/laser-erp-backup")
        if server_domain:
            ssh_exec(
                ssh,
                f"sed -i 's/server_name erp.example.ru;/server_name {server_domain};/' /etc/nginx/sites-available/laser-erp",
            )
        ssh_exec(ssh, "systemctl daemon-reload && systemctl enable laser-erp && systemctl restart laser-erp")
        ssh_exec(ssh, "nginx -t && systemctl reload nginx")
        ssh_exec(ssh, "systemctl --no-pager --full status laser-erp | sed -n '1,20p'", check=False)
        ssh_exec(ssh, "curl -I http://127.0.0.1/ || true", check=False)
        print(f"DEPLOY OK: http://{server_ip}/admin/")
    finally:
        sftp.close()
        ssh.close()


if __name__ == "__main__":
    main()
