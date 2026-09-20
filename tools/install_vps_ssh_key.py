#!/usr/bin/env python3
"""Write ~/.ssh/vps_key from VPS_SSH_PRIVATE_KEY without printing the key."""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

BEGIN = "-----BEGIN OPENSSH PRIVATE KEY-----"
END = "-----END OPENSSH PRIVATE KEY-----"
DEFAULT_PATHS = (
    Path.home() / ".ssh" / "vps_key",
    Path.home() / ".ssh" / "laser_erp_agent",
)


def normalize_openssh_private_key(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    if "\\n" in text and text.count("\n") <= 1:
        text = text.replace("\\n", "\n")
    text = text.strip()
    if BEGIN not in text or END not in text:
        raise ValueError("VPS_SSH_PRIVATE_KEY is not an OpenSSH private key PEM")
    body = text.split(BEGIN, 1)[1].split(END, 1)[0]
    b64 = "".join(body.split())
    if not b64:
        raise ValueError("OpenSSH private key body is empty")
    wrapped = "\n".join(textwrap.wrap(b64, 70))
    return f"{BEGIN}\n{wrapped}\n{END}\n"


def write_vps_ssh_key(raw: str | None = None, paths: tuple[Path, ...] = DEFAULT_PATHS) -> list[Path]:
    if raw is None:
        raw = os.environ.get("VPS_SSH_PRIVATE_KEY", "")
    if not raw.strip():
        raise ValueError("VPS_SSH_PRIVATE_KEY is not set")
    pem = normalize_openssh_private_key(raw)
    ssh_dir = Path.home() / ".ssh"
    ssh_dir.mkdir(mode=0o700, exist_ok=True)
    written: list[Path] = []
    for path in paths:
        path.write_text(pem)
        path.chmod(0o600)
        written.append(path)
    return written


def main() -> int:
    try:
        paths = write_vps_ssh_key()
    except ValueError as exc:
        print(exc)
        return 1
    print("wrote", " ".join(str(p) for p in paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
