"""
Устаревший вход: используйте команду Django:
  python manage.py ensure_counterparty_table
"""
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    subprocess.check_call(
        [sys.executable, str(root / "manage.py"), "ensure_counterparty_table"],
        cwd=str(root),
    )
