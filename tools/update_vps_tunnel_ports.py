#!/usr/bin/env python3
"""Update VPS tunnel key to allow SSH (22022) and RDP (3389) reverse forwards."""
from __future__ import annotations

from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
BEGIN, END = "# BEGIN HOME-PC-TUNNEL", "# END HOME-PC-TUNNEL"
SSH_PORT, RDP_PORT = "22022", "3389"

ENV = {}
for raw in (ROOT / ".env.server").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        ENV[k.strip()] = v.strip()

tunnel_pub = (Path.home() / ".ssh" / "id_ed25519_vps_tunnel.pub").read_text(encoding="utf-8").strip()
tunnel_line = (
    f'restrict,port-forwarding,permitlisten="127.0.0.1:{SSH_PORT}",'
    f'permitlisten="127.0.0.1:{RDP_PORT}" {tunnel_pub}'
)
block = f"{BEGIN}\n{tunnel_line}\n{END}"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(
    ENV["SERVER_IP"],
    port=int(ENV.get("SSH_PORT", "22")),
    username=ENV.get("SSH_USER", "root"),
    password=ENV["SSH_PASSWORD"],
    timeout=20,
)
sftp = ssh.open_sftp()
with sftp.open("/root/.ssh/authorized_keys", "r") as f:
    text = f.read().decode("utf-8", errors="replace")
if BEGIN in text and END in text:
    start = text.index(BEGIN)
    end = text.index(END) + len(END)
    text = text[:start].rstrip() + "\n" + block + "\n" + text[end:].lstrip()
else:
    if text and not text.endswith("\n"):
        text += "\n"
    text += block + "\n"
with sftp.open("/root/.ssh/authorized_keys", "w") as f:
    f.write(text)
sftp.close()
ssh.close()
print("VPS tunnel key updated for ports", SSH_PORT, RDP_PORT)
