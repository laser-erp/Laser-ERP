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
NGINX_TEMPLATE = ROOT / "deploy" / "nginx" / "laser-erp.conf"


def read_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def ssh_exec(ssh: paramiko.SSHClient, cmd: str, check: bool = True) -> str:
    print(f"REMOTE: {cmd}")
    _stdin, stdout, stderr = ssh.exec_command(cmd, timeout=120)
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
    sftp = ssh.open_sftp()
    try:
        ssh_exec(ssh, "cp /etc/nginx/sites-available/laser-erp /etc/nginx/sites-available/laser-erp.bak.$(date +%Y%m%d_%H%M%S)")
        sftp.put(str(NGINX_TEMPLATE), "/etc/nginx/sites-available/laser-erp")
        ssh_exec(ssh, "ln -sf /etc/nginx/sites-available/laser-erp /etc/nginx/sites-enabled/laser-erp")
        ssh_exec(ssh, "nginx -t")
        ssh_exec(ssh, "systemctl reload nginx")
        ssh_exec(ssh, "sed -n '1,220p' /etc/nginx/sites-enabled/laser-erp")
        print("TLS FIX APPLIED")
    finally:
        sftp.close()
        ssh.close()


if __name__ == "__main__":
    main()
