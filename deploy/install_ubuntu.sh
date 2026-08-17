#!/usr/bin/env bash
# Первичная установка Laser ERP на Ubuntu Server 22.04/24.04.
# Запуск: sudo bash deploy/install_ubuntu.sh
set -euo pipefail

APP_USER="${APP_USER:-lasererp}"
APP_DIR="${APP_DIR:-/var/www/laser-erp}"
REPO_URL="${REPO_URL:-https://github.com/laser-erp/Laser-ERP.git}"
ENV_FILE="/etc/laser-erp.env"

echo "==> Обновление пакетов..."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y

echo "==> Установка зависимостей..."
apt-get install -y python3 python3-venv python3-pip git nginx postgresql postgresql-contrib

if ! id "$APP_USER" &>/dev/null; then
  adduser --disabled-password --gecos "" "$APP_USER"
fi
usermod -aG www-data "$APP_USER" || true

mkdir -p "$APP_DIR" /var/backups/laser-erp
chown -R "$APP_USER:www-data" "$APP_DIR" /var/backups/laser-erp

if [[ ! -d "$APP_DIR/.git" ]]; then
  echo "==> Клонирование репозитория..."
  sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
else
  echo "==> Репозиторий уже есть, git pull..."
  sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only
fi

cd "$APP_DIR"
if [[ ! -d .venv ]]; then
  sudo -u "$APP_USER" python3 -m venv .venv
fi
sudo -u "$APP_USER" .venv/bin/pip install --upgrade pip
sudo -u "$APP_USER" .venv/bin/pip install -r requirements.txt

mkdir -p logs media staticfiles
chown -R "$APP_USER:www-data" logs media staticfiles
chmod 775 logs media staticfiles

if [[ ! -f "$ENV_FILE" ]]; then
  cp deploy/env.example "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo ""
  echo "!!! Создан $ENV_FILE — ОБЯЗАТЕЛЬНО отредактируйте DJANGO_SECRET_KEY, ALLOWED_HOSTS, POSTGRES_*"
  echo ""
fi

# PostgreSQL: создать БД, если заданы переменные в env
if grep -q '^POSTGRES_DB=' "$ENV_FILE" 2>/dev/null; then
  source "$ENV_FILE" || true
  if [[ -n "${POSTGRES_DB:-}" && -n "${POSTGRES_USER:-}" ]]; then
    echo "==> Настройка PostgreSQL..."
    sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='${POSTGRES_USER}'" | grep -q 1 \
      || sudo -u postgres psql -c "CREATE USER ${POSTGRES_USER} WITH PASSWORD '${POSTGRES_PASSWORD:-changeme}';"
    sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='${POSTGRES_DB}'" | grep -q 1 \
      || sudo -u postgres psql -c "CREATE DATABASE ${POSTGRES_DB} OWNER ${POSTGRES_USER};"
  fi
fi

echo "==> Django: migrate, collectstatic..."
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

cp deploy/systemd/laser-erp.service /etc/systemd/system/laser-erp.service
systemctl daemon-reload
systemctl enable laser-erp
systemctl restart laser-erp

cp deploy/nginx/laser-erp.conf /etc/nginx/sites-available/laser-erp
ln -sf /etc/nginx/sites-available/laser-erp /etc/nginx/sites-enabled/laser-erp
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

cp deploy/cron/laser-erp-backup /etc/cron.d/laser-erp-backup
chmod 644 /etc/cron.d/laser-erp-backup

echo ""
echo "Готово. Проверьте:"
echo "  1. Отредактируйте $ENV_FILE (SECRET_KEY, домен, пароль БД)"
echo "  2. systemctl status laser-erp"
echo "  3. Откройте http://<IP-сервера>/admin/"
echo "  4. Создайте суперпользователя: cd $APP_DIR && sudo -u $APP_USER .venv/bin/python manage.py createsuperuser"
echo "  5. HTTPS: certbot --nginx -d ваш-домен.ru"
