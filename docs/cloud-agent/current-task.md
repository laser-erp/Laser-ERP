# Задание для облачного агента (сервер)

**Обновлено локальным агентом:** 2026-09-20  
**Фаза плана:** 0.1 (доработка) — git на VPS для `deploy/update_ubuntu.sh`  
**Прошлое задание:** [archive/2026-09-20-phase0-vps-update.md](./archive/2026-09-20-phase0-vps-update.md)

---

## Статус

| Поле | Значение |
|------|----------|
| **Статус** | `waiting` |
| **Кто выполняет** | cloud-agent |
| **Блокер** | — |

---

## Цель

1. Сделать `/var/www/laser-erp` **git-репозиторием**, привязанным к **https://github.com/laser-erp/Laser-ERP** (ветка **main**).
2. Добиться успешного **`sudo bash deploy/update_ubuntu.sh`** (или `git pull --ff-only` от пользователя `lasererp`).
3. **Не удалять** `media/`, `logs/`, `.venv/`, `/etc/laser-erp.env` — они в `.gitignore` или вне каталога.
4. Кратко описать в отчёте, как дальше обновлять сервер (git pull vs rsync).

---

## Предусловия

- SSH: `VPS_HOST` / `VPS_USER` / `VPS_PASSWORD` (как в прошлом задании) или исправленный ключ.
- **Не запускать** `tools/_deploy_server.py`.
- Каталог приложения: `/var/www/laser-erp`, пользователь: `lasererp`.
- Если репозиторий **приватный** — в Secrets нужен **`GITHUB_TOKEN`** (PAT только `repo`) для `git fetch`/`pull` под пользователем `lasererp`. Токен **не писать в отчёт**.

---

## Шаги

### 1. Снимок «до»

```bash
systemctl is-active laser-erp nginx
ls -la /var/www/laser-erp/.git 2>/dev/null || echo "NO_GIT"
du -sh /var/www/laser-erp/media /var/www/laser-erp/logs 2>/dev/null || true
curl -sS -o /dev/null -w "admin_login=%{http_code}\n" https://laser-erp.armada.sx/admin/login/
```

### 2. Инициализация git (если NO_GIT)

Выполнять **от root**, команды git — **от lasererp**:

```bash
APP=/var/www/laser-erp
sudo -u lasererp bash -lc "cd $APP && git init -b main"
sudo -u lasererp bash -lc "cd $APP && git remote add origin https://github.com/laser-erp/Laser-ERP.git"
```

Если `remote origin already exists` — проверить URL и перейти к fetch.

**Приватный GitHub** (если `git fetch` просит логин):

```bash
# GITHUB_TOKEN — из Secrets, не логировать
sudo -u lasererp bash -lc "cd $APP && git remote set-url origin https://x-access-token:${GITHUB_TOKEN}@github.com/laser-erp/Laser-ERP.git"
```

### 3. Подтянуть main без потери media/logs

```bash
APP=/var/www/laser-erp
sudo -u lasererp bash -lc "cd $APP && git fetch origin main"
sudo -u lasererp bash -lc "cd $APP && git reset --hard origin/main"
sudo -u lasererp bash -lc "cd $APP && git branch --set-upstream-to=origin/main main"
sudo -u lasererp bash -lc "cd $APP && git rev-parse --short HEAD"
```

После `reset --hard` проверить, что **media** и **logs** на месте (они должны остаться как неотслеживаемые/игнорируемые).

Если `reset --hard` неприемлем из-за локальных правок на сервере — в отчёте описать diff и статус **`blocked`**, предложить вариант **только rsync** (см. шаг 6).

### 4. Права

```bash
chown -R lasererp:www-data /var/www/laser-erp
find /var/www/laser-erp -type d -exec chmod 775 {} \;
find /var/www/laser-erp -type f -exec chmod 664 {} \;
# .venv и manage.py — как было на сервере; при сомнениях не менять исполняемость .venv/bin/*
```

### 5. Проверка update_ubuntu.sh

```bash
cd /var/www/laser-erp
sudo bash deploy/update_ubuntu.sh
```

Ожидаемо: `git pull --ff-only` успешен (или «Already up to date»), migrate/collectstatic/restart без ошибок.

Повторно:

```bash
curl -sS -o /dev/null -w "admin_login=%{http_code}\n" https://laser-erp.armada.sx/admin/login/
```

### 6. Документация (в репозитории)

Добавить файл **`docs/cloud-agent/server-update.md`** (кратко, по-русски):

- штатная команда на VPS: `sudo bash /var/www/laser-erp/deploy/update_ubuntu.sh` после **выложить на GitHub** с **main**;
- запасной путь: rsync / `tools/_sync_vps_code.py` с машины, где есть `.env.server`;
- что **не** делать: `_deploy_server.py`.

Сохранить файл в истории проекта и **выложить на GitHub** вместе с отчётом.

### 7. (Опционально) Deploy key

Если PAT неудобен — настроить read-only deploy key для `lasererp`, **не коммитить** приватный ключ; в отчёте только «deploy key установлен: да/нет».

---

## Критерий «готово»

- [ ] `git rev-parse` в `/var/www/laser-erp` показывает коммит с **main** GitHub.
- [ ] `deploy/update_ubuntu.sh` завершился **OK**.
- [ ] `/admin/login/` по-прежнему **200/302**, не **500**.
- [ ] Файл **`docs/cloud-agent/server-update.md`** создан.
- [ ] Отчёт ниже заполнен и **выложен на GitHub**.

---

## Отчёт облачного агента

### Дата и время

### Git: коммит на сервере, upstream

### update_ubuntu.sh: вывод (последние ~20 строк)

### admin_login HTTP-код после работ

### media/ и logs/ на месте (да/нет, размеры)

### Статус финальный

`done` | `blocked` — …

### Что нужно от владельца / локального агента

---

*Конец задания.*
