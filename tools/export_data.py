#!/usr/bin/env python3
"""
Экспорт данных Django для переноса на сервер.
Запуск из корня: python tools/export_data.py
Создаёт: бекапы/data_export_ГГГГ-ММ-ДД.json
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import django
from django.core.management import call_command


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)
    sys.path.insert(0, str(root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "laser_erp.settings")
    django.setup()
    out_dir = root / "бекапы"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"data_export_{date.today().isoformat()}.json"
    print("Экспорт:", out_file)
    with out_file.open("w", encoding="utf-8") as fh:
        call_command(
            "dumpdata",
            natural_foreign=True,
            natural_primary=True,
            indent=2,
            stdout=fh,
        )
    print("OK:", out_file)


if __name__ == "__main__":
    main()
