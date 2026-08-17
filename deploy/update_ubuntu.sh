#!/usr/bin/env bash
# Обновление Laser ERP на сервере после git push.
# Запуск из корня проекта: sudo bash deploy/update_ubuntu.sh
set -euo pipefail

APP_USER="${APP_USER:-lasererp}"
APP_DIR="${APP_DIR:-/var/www/laser-erp}"
ENV_FILE="/etc/laser-erp.env"

cd "$APP_DIR"
sudo -u "$APP_USER" git pull --ff-only
sudo -u "$APP_USER" .venv/bin/pip install -r requirements.txt
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
# Ubuntu sudo -E drops POSTGRES_* (env_reset) → Django would migrate SQLite, not gunicorn's Postgres.
django_as_app() {
  sudo -u "$APP_USER" env \
    DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE}" \
    DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY}" \
    DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS:-}" \
    DJANGO_DEBUG="${DJANGO_DEBUG:-0}" \
    POSTGRES_DB="${POSTGRES_DB}" \
    POSTGRES_USER="${POSTGRES_USER}" \
    POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
    POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}" \
    POSTGRES_PORT="${POSTGRES_PORT:-5432}" \
    "$@"
}
django_as_app .venv/bin/python manage.py migrate --noinput
django_as_app .venv/bin/python manage.py collectstatic --noinput
systemctl restart laser-erp
echo "OK: Laser ERP обновлён и перезапущен."
