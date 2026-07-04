#!/usr/bin/env python3
"""
Создаёт архив проекта в папку «бекапы/бэкап_ГГГГ-ММ-ДД/».
Исключает: .venv, __pycache__, .git, бекапы, .cursor, node_modules, *.pyc
Запуск из корня проекта: python tools/create_project_backup.py
"""
from __future__ import annotations

import os
import zipfile
from datetime import date
from pathlib import Path


SKIP_DIRS = frozenset(
    {
        ".venv",
        "__pycache__",
        ".git",
        "бекапы",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)
SKIP_SUFFIXES = frozenset({".pyc", ".pyo"})


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)
    today = date.today().isoformat()
    folder_name = f"бэкап_{today}"
    backup_root = root / "бекапы" / folder_name
    backup_root.mkdir(parents=True, exist_ok=True)
    zip_name = f"proekt_backup_{today}.zip"
    zip_path = backup_root / zip_name

    def rel_parts(p: Path) -> tuple[str, ...]:
        try:
            return p.relative_to(root).parts
        except ValueError:
            return ()

    def skip_path(p: Path) -> bool:
        parts = set(rel_parts(p))
        if parts & SKIP_DIRS:
            return True
        if p.suffix.lower() in SKIP_SUFFIXES:
            return True
        return False

    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(root):
            dp = Path(dirpath)
            rel = rel_parts(dp)
            if any(part in SKIP_DIRS for part in rel):
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                fp = dp / name
                if fp.resolve() == zip_path.resolve():
                    continue
                rel_file = rel_parts(fp)
                if not rel_file or any(part in SKIP_DIRS for part in rel_file):
                    continue
                if fp.suffix.lower() in SKIP_SUFFIXES:
                    continue
                zf.write(fp, Path(*rel_file).as_posix())
                count += 1

    readme = backup_root / "README_восстановление.txt"
    readme.write_text(
        f"Бэкап проекта: {today}\n\n"
        "Восстановление:\n"
        f"1. Скопируйте архив {zip_name} в нужное место.\n"
        "2. Распакуйте ZIP поверх пустой папки проекта или замените файлы.\n"
        "3. Создайте окружение: python -m venv .venv\n"
        "4. Активируйте venv и установите зависимости: pip install -r requirements.txt\n\n"
        "Исключено из архива: .venv, __pycache__, .git, папка бекапы, node_modules.\n",
        encoding="utf-8",
    )
    print(f"OK: {zip_path}")
    print(f"Файлов в архиве: {count}")


if __name__ == "__main__":
    main()
