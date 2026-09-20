#!/usr/bin/env python3
"""Push EMAIL_* from .env.server into /etc/laser-erp.env and restart gunicorn."""
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
EMAIL_KEYS = (
    "EMAIL_HOST",
    "EMAIL_PORT",
    "EMAIL_USE_SSL",
    "EMAIL_USE_TLS",
    "EMAIL_HOST_USER",
    "EMAIL_HOST_PASSWORD",
    "DEFAULT_FROM_EMAIL",
    "EMAIL_BACKEND",
    "EMAIL_TIMEOUT",
)


def read_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def upsert_env_text(text: str, updates: dict[str, str]) -> str:
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
    missing = [k for k in EMAIL_KEYS if k in updates and k not in seen]
    if missing:
        if out and out[-1].strip():
            out.append("")
        out.append("# --- SMTP Laser ERP ---")
        for key in missing:
            out.append(f"{key}={updates[key]}")
    return "\n".join(out) + "\n"


def main() -> None:
    env = read_env(ENV_FILE)
    updates = {k: env[k] for k in EMAIL_KEYS if k in env and env[k] != ""}
    # Allow empty password only if explicitly present — but refuse deploy without it.
    if "EMAIL_HOST_PASSWORD" in env:
        updates["EMAIL_HOST_PASSWORD"] = env["EMAIL_HOST_PASSWORD"]
    required = ("EMAIL_HOST", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD", "DEFAULT_FROM_EMAIL")
    missing = [k for k in required if not updates.get(k)]
    if missing:
        raise SystemExit(
            "В .env.server не заполнены: "
            + ", ".join(missing)
            + ". Для Яндекса нужен пароль приложения: https://id.yandex.ru/security/app-passwords"
        )

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
        remote_env = "/etc/laser-erp.env"
        with sftp.file(remote_env, "r") as f:
            current = f.read().decode("utf-8", errors="replace")
        backup = remote_env + ".bak.email"
        ssh.exec_command(f"cp {remote_env} {backup}")
        new_text = upsert_env_text(current, updates)
        with sftp.file(remote_env, "w") as f:
            f.write(new_text)
        print(f"Updated {remote_env} (backup {backup})")
        for cmd in (
            "systemctl restart laser-erp",
            "systemctl --no-pager --full status laser-erp | sed -n '1,12p'",
        ):
            print(f"REMOTE: {cmd}")
            _stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
            print(stdout.read().decode("utf-8", errors="replace"))
            err = stderr.read().decode("utf-8", errors="replace")
            if err.strip():
                print(err, file=sys.stderr)
            if stdout.channel.recv_exit_status() != 0 and "status" not in cmd:
                raise RuntimeError(cmd)
        print("EMAIL CONFIG APPLIED")
    finally:
        sftp.close()
        ssh.close()


if __name__ == "__main__":
    main()
