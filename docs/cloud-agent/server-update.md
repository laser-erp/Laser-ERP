# Обновление Laser ERP на VPS

Краткая инструкция для владельца и локального агента. Секреты (пароли, токены) **не хранятся в GitHub**.

## Штатный способ (после настройки git)

1. Локально: сохранить изменения в истории проекта и **выложить на GitHub** в ветку **main**.
2. На сервере (SSH под `root`):

```bash
cd /var/www/laser-erp
sudo bash deploy/update_ubuntu.sh
```

Скрипт выполняет от имени `lasererp`:

- `git pull --ff-only` (ветка **main**);
- `pip install -r requirements.txt`;
- `migrate`, `collectstatic`;
- перезапуск `systemctl restart laser-erp`.

Проверка:

```bash
curl -sS -o /dev/null -w "%{http_code}\n" https://laser-erp.armada.sx/admin/login/
```

Ожидаемо **200** или **302**, не **500**.

### Git на сервере

- Каталог: `/var/www/laser-erp`
- Remote: `https://github.com/laser-erp/Laser-ERP.git`
- Пользователь git-команд: `lasererp`
- Ветка: `main`, отслеживает `origin/main`

Если репозиторий станет **приватным**, на сервере нужен read-only **deploy key** или PAT в URL remote (настраивается на VPS, **не коммитить**). Для облачного агента — секрет `GITHUB_TOKEN` в Cursor.

## Что не трогать при обновлении

- `media/` — загрузки пользователей
- `logs/` — журналы gunicorn и Django
- `.venv/` — виртуальное окружение Python
- `/etc/laser-erp.env` — секреты Django и Postgres (вне репозитория)

Они в `.gitignore` или вне каталога приложения; `git pull` / `reset --hard origin/main` их **не удаляет**.

## Запасной путь (без git)

Если `git pull` недоступен:

- с машины, где есть `.env.server`: `python tools/_sync_vps_code.py`;
- или rsync из клона репозитория (исключая `.venv`, `media`, `logs`, `db.sqlite3`).

После rsync вручную:

```bash
set -a && source /etc/laser-erp.env && set +a
cd /var/www/laser-erp
sudo -u lasererp .venv/bin/pip install -r requirements.txt
# migrate + collectstatic как в deploy/update_ubuntu.sh
systemctl restart laser-erp
```

## Нельзя без явного указания владельца

- **`tools/_deploy_server.py`** — затирает каталог и делает `loaddata` (полная перезаливка данных).

## См. также

- [README.md](./README.md) — роли локального и облачного агента
- [current-task.md](./current-task.md) — текущее задание для cloud-agent
