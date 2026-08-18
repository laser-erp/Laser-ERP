#!/usr/bin/env python3
"""
SSH to the home Windows PC via the existing VPS, without opening port 22 to the internet.

- OpenSSH Server listens only on 127.0.0.1
- reverse tunnel: VPS 127.0.0.1:22022 -> home 127.0.0.1:22
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import paramiko

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.server"
TUNNEL_PORT = "22022"
MARKER_BEGIN = "# BEGIN HOME-PC-TUNNEL"
MARKER_END = "# END HOME-PC-TUNNEL"


def read_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("LOCAL:", " ".join(cmd))
    return subprocess.run(cmd, check=check)


def ensure_key(path: Path, comment: str) -> None:
    if path.exists() and path.with_suffix(path.suffix + ".pub").exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            r"C:\Windows\System32\OpenSSH\ssh-keygen.exe",
            "-t",
            "ed25519",
            "-f",
            str(path),
            "-N",
            "",
            "-C",
            comment,
        ]
    )


def replace_marked_block(text: str, block: str) -> str:
    if MARKER_BEGIN in text and MARKER_END in text:
        start = text.index(MARKER_BEGIN)
        end = text.index(MARKER_END) + len(MARKER_END)
        return text[:start].rstrip() + "\n" + block + "\n" + text[end:].lstrip()
    if text and not text.endswith("\n"):
        text += "\n"
    return text + block + "\n"


def ssh_exec(ssh: paramiko.SSHClient, cmd: str, check: bool = True) -> str:
    print("REMOTE:", cmd)
    _stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.strip())
    if err.strip():
        print(err.strip(), file=sys.stderr)
    if check and code != 0:
        raise RuntimeError(f"Remote command failed ({code}): {cmd}")
    return out


def main() -> None:
    env = read_env(ENV_FILE)
    server_ip = env["SERVER_IP"]
    server_domain = (env.get("SERVER_DOMAIN") or server_ip).strip()
    ssh_user = env.get("SSH_USER", "root")
    ssh_port = int(env.get("SSH_PORT", "22"))
    ssh_password = env.get("SSH_PASSWORD", "")
    if not ssh_password:
        raise RuntimeError("SSH_PASSWORD is empty in .env.server")

    home_ssh = Path.home() / ".ssh"
    home_ssh.mkdir(parents=True, exist_ok=True)
    tunnel_key = home_ssh / "id_ed25519_vps_tunnel"
    login_key = home_ssh / "id_ed25519_home"
    ensure_key(tunnel_key, "desctop-house-tunnel")
    ensure_key(login_key, "desctop-house-login")

    login_pub = login_key.with_suffix(login_key.suffix + ".pub").read_text(encoding="utf-8").strip()
    tunnel_pub = tunnel_key.with_suffix(tunnel_key.suffix + ".pub").read_text(encoding="utf-8").strip()

    auth_keys = home_ssh / "authorized_keys"
    existing = auth_keys.read_text(encoding="utf-8") if auth_keys.exists() else ""
    if login_pub not in existing:
        with auth_keys.open("a", encoding="utf-8", newline="\n") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write(login_pub + "\n")
    os.chmod(auth_keys, 0o600)

    installer = ROOT / "tools" / "setup_home_ssh.ps1"
    print("Need Administrator once: install OpenSSH Server (UAC prompt).")
    elevated = run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Start-Process powershell -Verb RunAs -Wait -PassThru "
                f"-ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"{installer}\"' "
                "| Select-Object -ExpandProperty ExitCode"
            ),
        ],
        check=False,
    )
    if elevated.returncode not in (0, None):
        print("OpenSSH install may have failed or UAC was cancelled.", file=sys.stderr)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(server_ip, port=ssh_port, username=ssh_user, password=ssh_password, timeout=20)
    sftp = ssh.open_sftp()
    try:
        ssh_exec(ssh, "mkdir -p /root/home-pc-ssh /root/.ssh && chmod 700 /root/.ssh")
        auth_remote = "/root/.ssh/authorized_keys"
        try:
            with sftp.open(auth_remote, "r") as rf:
                remote_auth = rf.read().decode("utf-8", errors="replace")
        except OSError:
            remote_auth = ""
        tunnel_line = (
            f'restrict,port-forwarding,permitlisten="127.0.0.1:{TUNNEL_PORT}" {tunnel_pub}'
        )
        block = f"{MARKER_BEGIN}\n{tunnel_line}\n{MARKER_END}"
        new_auth = replace_marked_block(remote_auth, block)
        with sftp.open(auth_remote, "w") as wf:
            wf.write(new_auth)
        ssh_exec(ssh, "chmod 600 /root/.ssh/authorized_keys")

        sftp.put(str(login_key), "/root/home-pc-ssh/id_ed25519_home")
        sftp.put(str(login_key.with_name(login_key.name + ".pub")), "/root/home-pc-ssh/id_ed25519_home.pub")
        ssh_exec(ssh, "chmod 600 /root/home-pc-ssh/id_ed25519_home && chmod 644 /root/home-pc-ssh/id_ed25519_home.pub")
        ssh_exec(
            ssh,
            "grep -E '^(AllowTcpForwarding|GatewayPorts|PermitListen)' /etc/ssh/sshd_config || true",
            check=False,
        )
    finally:
        sftp.close()
        ssh.close()

    task_name = "LaserHomeSshTunnel"
    tunnel_ps1 = ROOT / "tools" / "start_home_ssh_tunnel.ps1"
    run(
        [
            "schtasks",
            "/Create",
            "/TN",
            task_name,
            "/SC",
            "ONLOGON",
            "/RL",
            "LIMITED",
            "/F",
            "/TR",
            (
                f'powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass '
                f'-File "{tunnel_ps1}"'
            ),
        ],
        check=False,
    )
    run(["schtasks", "/Run", "/TN", task_name], check=False)

    win_user = os.environ.get("USERNAME", "USER")
    example = ROOT / "tools" / "home_ssh_config.example"
    example.write_text(
        f"""# Put this on the laptop: ~/.ssh/config
# Copy the key first:
#   scp -P {ssh_port} {ssh_user}@{server_domain}:/root/home-pc-ssh/id_ed25519_home ~/.ssh/id_ed25519_home
#   chmod 600 ~/.ssh/id_ed25519_home

Host laser-vps
  HostName {server_domain}
  User {ssh_user}
  Port {ssh_port}

Host home-pc
  HostName 127.0.0.1
  User {win_user}
  Port {TUNNEL_PORT}
  ProxyJump laser-vps
  IdentityFile ~/.ssh/id_ed25519_home
  IdentitiesOnly yes
""",
        encoding="utf-8",
    )
    print()
    print("Ready. From another computer:")
    print(f"  1) scp -P {ssh_port} {ssh_user}@{server_domain}:/root/home-pc-ssh/id_ed25519_home ~/.ssh/id_ed25519_home")
    print("  2) Cursor: Remote-SSH -> home-pc  (see tools/home_ssh_config.example)")
    print(f"  3) ssh -J {ssh_user}@{server_domain} -p {TUNNEL_PORT} {win_user}@127.0.0.1")
    print("Keep this Windows session on (Win+L is OK). Do not Shut down / Sign out.")


if __name__ == "__main__":
    main()
