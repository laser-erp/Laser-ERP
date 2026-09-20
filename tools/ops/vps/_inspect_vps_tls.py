#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def read_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


_TOOLS = Path(__file__).resolve().parents[2]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
from project_root import PROJECT_ROOT as ROOT
ENV_FILE = ROOT / ".env.server"


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
    commands = [
        "nginx -T 2>/dev/null | sed -n '1,260p'",
        "grep -R -n 'laser-erp.armada.sx\\|ssl_certificate\\|listen 443\\|server_name' /etc/nginx/sites-available /etc/nginx/sites-enabled /etc/nginx/conf.d /etc/nginx/vhosts 2>/dev/null || true",
        "sed -n '1,260p' /etc/nginx/sites-enabled/laser-erp 2>/dev/null || true",
        "sed -n '1,260p' /etc/letsencrypt/options-ssl-nginx.conf 2>/dev/null || true",
        "ls -l /etc/letsencrypt/live/laser-erp.armada.sx || true",
        "openssl x509 -in /etc/letsencrypt/live/laser-erp.armada.sx/fullchain.pem -noout -subject -issuer -dates || true",
        "ss -ltnp | grep :443 || true",
    ]
    try:
        for cmd in commands:
            print(f"---CMD--- {cmd}")
            _stdin, stdout, stderr = ssh.exec_command(cmd, timeout=90)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            if out.strip():
                print(out)
            if err.strip():
                print(err, file=sys.stderr)
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
