#!/usr/bin/env python3
"""
Серверный бэкап: PostgreSQL (если настроен) + media + dumpdata.
Запуск на Ubuntu (cron): .venv/bin/python tools/backup_server.py
Папка: /var/backups/laser-erp/ или BACKUP_DIR из окружения.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "laser_erp.settings_prod")

    today = date.today().isoformat()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = Path(os.environ.get("BACKUP_DIR", "/var/backups/laser-erp"))
    day_dir = backup_root / today
    day_dir.mkdir(parents=True, exist_ok=True)

    pg_db = os.environ.get("POSTGRES_DB", "").strip()
    if pg_db:
        pg_user = os.environ.get("POSTGRES_USER", "lasererp")
        pg_host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
        pg_port = os.environ.get("POSTGRES_PORT", "5432")
        sql_path = day_dir / f"postgres_{stamp}.dump"
        env = os.environ.copy()
        if os.environ.get("POSTGRES_PASSWORD"):
            env["PGPASSWORD"] = os.environ["POSTGRES_PASSWORD"]
        with open(sql_path, "wb") as out:
            dump = subprocess.run(
                [
                    "pg_dump",
                    "-h",
                    pg_host,
                    "-p",
                    pg_port,
                    "-U",
                    pg_user,
                    "-Fc",
                    pg_db,
                ],
                env=env,
                stdout=out,
                stderr=subprocess.PIPE,
                check=False,
            )
        if dump.returncode != 0:
            print("pg_dump failed:", dump.stderr.decode("utf-8", errors="replace"), file=sys.stderr)
        else:
            print("OK postgres:", sql_path)

    media = root / "media"
    if media.is_dir() and any(media.iterdir()):
        media_archive = shutil.make_archive(
            str(day_dir / f"media_{stamp}"),
            "zip",
            root_dir=media,
        )
        print("OK media:", media_archive)

    json_path = day_dir / f"dumpdata_{stamp}.json"
    subprocess.run(
        [sys.executable, "manage.py", "dumpdata", "--natural-foreign", "--natural-primary", "-o", str(json_path)],
        check=False,
    )
    if json_path.is_file():
        print("OK dumpdata:", json_path)

    # Удалить бэкапы старше 14 дней
    keep_days = int(os.environ.get("BACKUP_KEEP_DAYS", "14"))
    for child in backup_root.iterdir():
        if not child.is_dir():
            continue
        try:
            folder_date = date.fromisoformat(child.name)
        except ValueError:
            continue
        if (date.today() - folder_date).days > keep_days:
            shutil.rmtree(child, ignore_errors=True)
            print("Removed old backup:", child)


if __name__ == "__main__":
    main()
