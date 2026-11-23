# Обновление Laser ERP на VPS

Краткая инструкция для владельца и локального агента. Секреты (пароли, токены) **не хранятся в GitHub**.

## Выкладчик (автодеплой) — основной способ

На сервере работает свой выкладчик `deploy/autodeploy.sh` (systemd-таймер, раз в 2 минуты).
Он **не зависит от GitHub Actions** и его лимита минут: сервер сам забирает `main`.

Что он делает при новом коммите в `main`:

1. **Блокирует** миграции, удаляющие данные (`DeleteModel`, `RemoveField`, `DROP`). Такие выкатывать только вручную:
   `sudo ALLOW_DESTRUCTIVE=1 bash /var/www/laser-erp/deploy/autodeploy.sh`.
2. **Гоняет все тесты** на чистой копии коммита (SQLite, боевая база не трогается). Красные — не выкатывает
   и не повторяет этот коммит, пока не придёт новый.
3. Если есть новые миграции — **бэкап базы** (`tools/backup_server.py`), без бэкапа выкладки нет.
4. `deploy/update_ubuntu.sh` (pull, pip, migrate, collectstatic, restart).
5. Проверяет `/healthz/`. Если сайт не поднялся и миграций не было — **откат на прошлый коммит**.

Итог виден всем, без входа: `https://laser-erp.armada.sx/healthz/` → `commit` и `last_deploy.state`
(`ok`, `testing`, `tests_failed`, `blocked`, `rolled_back`, `failed`).
Журналы: `logs/autodeploy.log`, `logs/autodeploy-tests.log`.

### Установка (один раз, под root)

```bash
cd /var/www/laser-erp && sudo bash deploy/update_ubuntu.sh
cp deploy/systemd/laser-erp-autodeploy.service deploy/systemd/laser-erp-autodeploy.timer /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now laser-erp-autodeploy.timer
systemctl list-timers laser-erp-autodeploy.timer
```

Выключить: `systemctl disable --now laser-erp-autodeploy.timer`.

## Ручной способ

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
