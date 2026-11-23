#!/usr/bin/env bash
# Выкладчик Laser ERP: сам забирает новые коммиты из main и выкатывает их.
# Запускается systemd-таймером laser-erp-autodeploy.timer (раз в 2 минуты) от root.
# Ручной запуск: sudo bash /var/www/laser-erp/deploy/autodeploy.sh
#
# Защита:
#  - один запуск за раз (flock);
#  - миграции, удаляющие таблицы/поля (DeleteModel, RemoveField, DROP), НЕ выкатываются —
#    нужен ручной запуск с ALLOW_DESTRUCTIVE=1;
#  - перед новыми миграциями — бэкап базы (tools/backup_server.py);
#  - после рестарта — проверка /healthz/; если сайт не поднялся и миграций не было —
#    откат на прошлый коммит;
#  - итог пишется в logs/deploy-status.json и виден на https://<сайт>/healthz/.
set -uo pipefail

# git pull перезаписывает этот файл, а bash читает скрипт по ходу выполнения —
# поэтому работаем с копией.
if [ -z "${AUTODEPLOY_COPY:-}" ]; then
  cp "$0" /run/laser-erp-autodeploy.sh
  AUTODEPLOY_COPY=1 exec bash /run/laser-erp-autodeploy.sh "$@"
fi

APP_USER="${APP_USER:-lasererp}"
APP_DIR="${APP_DIR:-/var/www/laser-erp}"
ENV_FILE="${ENV_FILE:-/etc/laser-erp.env}"
BRANCH="${BRANCH:-main}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8001/healthz/}"
LOG_DIR="$APP_DIR/logs"
LOG="$LOG_DIR/autodeploy.log"
STATUS="$LOG_DIR/deploy-status.json"

mkdir -p "$LOG_DIR"
exec 9>/run/laser-erp-autodeploy.lock
flock -n 9 || exit 0

log() { echo "$(date -Is) $*" >>"$LOG"; }
as_app() { sudo -u "$APP_USER" "$@"; }
status() { # status <state> <commit> <message>
  local msg="${3//\"/\'}"
  printf '{"state":"%s","commit":"%s","at":"%s","message":"%s"}\n' \
    "$1" "$2" "$(date -Is)" "$msg" >"$STATUS"
  chown "$APP_USER" "$STATUS" 2>/dev/null || true
}

cd "$APP_DIR" || exit 1
as_app git fetch -q origin "$BRANCH" || { log "fetch failed"; exit 1; }
OLD=$(as_app git rev-parse HEAD)
NEW=$(as_app git rev-parse "origin/$BRANCH")
[ "$OLD" = "$NEW" ] && exit 0
# этот коммит уже не прошёл тесты — не гоняем их заново каждые 2 минуты
[ -f "$LOG_DIR/autodeploy-failed-sha" ] && [ "$(cat "$LOG_DIR/autodeploy-failed-sha")" = "$NEW" ] && exit 0

log "new commit: $OLD -> $NEW"
status deploying "$NEW" "выкатываю"

NEW_MIGRATIONS=$(as_app git diff --name-only --diff-filter=A "$OLD" "$NEW" -- '*/migrations/0*.py')
if [ -n "$NEW_MIGRATIONS" ] && [ "${ALLOW_DESTRUCTIVE:-0}" != "1" ]; then
  # shellcheck disable=SC2086
  DANGEROUS=$(as_app git diff "$OLD" "$NEW" -- $NEW_MIGRATIONS 2>/dev/null \
    | grep -iE '^\+.*(DeleteModel|RemoveField|DROP (TABLE|COLUMN))' || true)
  if [ -n "$DANGEROUS" ]; then
    log "BLOCKED: destructive migrations in $NEW: $NEW_MIGRATIONS"
    status blocked "$OLD" "в $NEW есть миграции с удалением данных; нужен ручной запуск с ALLOW_DESTRUCTIVE=1"
    exit 1
  fi
fi

# Тесты прямо на сервере (свой CI, без минут GitHub): чистая копия коммита,
# SQLite-база для тестов, боевая база не трогается.
TEST_DIR="/var/tmp/laser-erp-test"
log "running tests for $NEW"
status testing "$NEW" "гоняю тесты"
as_app git worktree remove --force "$TEST_DIR" 2>/dev/null; rm -rf "$TEST_DIR"
as_app git worktree prune
as_app git worktree add -q --detach "$TEST_DIR" "$NEW" >>"$LOG" 2>&1
as_app .venv/bin/pip install -q -r "$TEST_DIR/requirements.txt" >>"$LOG" 2>&1
if ! (cd "$TEST_DIR" && as_app env DJANGO_SETTINGS_MODULE=laser_erp.settings \
      timeout 900 "$APP_DIR/.venv/bin/python" manage.py test --noinput >"$LOG_DIR/autodeploy-tests.log" 2>&1); then
  as_app git worktree remove --force "$TEST_DIR" 2>/dev/null
  echo "$NEW" >"$LOG_DIR/autodeploy-failed-sha"
  log "TESTS FAILED for $NEW, see logs/autodeploy-tests.log"
  status tests_failed "$OLD" "тесты не прошли на $NEW: $(grep -E '^(FAIL|ERROR):|Error|FAILED' "$LOG_DIR/autodeploy-tests.log" | head -n 4 | tr '\n' ' ')"
  exit 1
fi
as_app git worktree remove --force "$TEST_DIR" 2>/dev/null
log "tests passed for $NEW"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [ -n "$NEW_MIGRATIONS" ]; then
  log "backup before migrations: $NEW_MIGRATIONS"
  if ! as_app env DJANGO_SETTINGS_MODULE=laser_erp.settings_prod \
      POSTGRES_DB="${POSTGRES_DB:-}" POSTGRES_USER="${POSTGRES_USER:-}" \
      POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}" POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}" \
      POSTGRES_PORT="${POSTGRES_PORT:-5432}" DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-}" \
      .venv/bin/python tools/backup_server.py >>"$LOG" 2>&1; then
    log "backup FAILED, deploy aborted"
    status failed "$OLD" "бэкап перед миграциями не удался, выкладка отменена"
    exit 1
  fi
fi

HEALTH_HOST="${DJANGO_ALLOWED_HOSTS%%,*}"
HEALTH_HOST="${HEALTH_HOST:-localhost}"
healthy() {
  for _ in $(seq 1 15); do
    curl -fsS -o /dev/null 2>/dev/null --max-time 5 -H "Host: $HEALTH_HOST" \
      -H "X-Forwarded-Proto: https" "$HEALTH_URL" && return 0
    sleep 2
  done
  return 1
}

rollback() { # rollback <причина>
  if [ -n "$NEW_MIGRATIONS" ]; then
    log "$1; migrations were involved, no automatic rollback"
    status failed "$NEW" "$1; были миграции — автоматический откат небезопасен, нужен человек (бэкап сделан перед выкладкой)"
    exit 1
  fi
  log "$1; rolling back to $OLD"
  as_app git reset -q --hard "$OLD"
  as_app .venv/bin/pip install -q -r requirements.txt >>"$LOG" 2>&1
  systemctl restart laser-erp
  if healthy; then
    echo "$NEW" >"$LOG_DIR/autodeploy-failed-sha"
    status rolled_back "$OLD" "$1 на $NEW — откатил на прошлый коммит"
  else
    status failed "$OLD" "$1 на $NEW, откат тоже не поднялся — нужен человек"
  fi
  exit 1
}

if ! bash deploy/update_ubuntu.sh >>"$LOG" 2>&1; then
  rollback "update_ubuntu.sh упал (см. logs/autodeploy.log)"
fi
NEW=$(as_app git rev-parse HEAD)  # pull мог забрать и более свежий коммит

if healthy; then
  log "OK: $NEW"
  status ok "$NEW" "выкачено"
  exit 0
fi
rollback "сайт не отвечает после рестарта"
