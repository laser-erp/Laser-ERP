"""Общий корень Django-проекта для скриптов в tools/."""
from __future__ import annotations

from pathlib import Path


def get_project_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "manage.py").is_file():
            return candidate
    raise RuntimeError("manage.py not found above tools/")


PROJECT_ROOT = get_project_root()
