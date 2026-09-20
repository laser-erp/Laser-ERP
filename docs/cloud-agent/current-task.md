# Задание для облачного агента (сервер)

**Обновлено локальным агентом:** 2026-09-21  
**Релиз:** техкарта — лазерная резка/гравировка, миграции `0133`–`0136`  
**Прошлое задание:** [archive/2026-09-20-phase0-vps-update.md](./archive/2026-09-20-phase0-vps-update.md) (git на VPS — `done`)

---

## Статус

| Поле | Значение |
|------|----------|
| **Статус** | `waiting` |
| **Кто выполняет** | cloud-agent |
| **Блокер** | — |

---

## Цель

После **выложить на GitHub** в **main** подтянуть код на боевой сервер и применить **миграции Postgres**, чтобы на **https://laser-erp.armada.sx** работали:

- один лист на техкарте таблички (без тройного учёта);
- этап **«Лазерная резка»** — только метры, без материала;
- этап **«Лазерная гравировка»** — тип контур/заливка, ₽/м и ₽/м² на карточке этапа;
- обновлённый интерфейс вкладки «Материалы» техкарты.

**Не запускать** `tools/_deploy_server.py` (затирает каталог и loaddata).

---

## Предусловия

- SSH: `VPS_HOST` / `VPS_USER` / `VPS_PASSWORD` (или ключ).
- Каталог: `/var/www/laser-erp`, пользователь `lasererp`, env: `/etc/laser-erp.env`.
- Репозиторий: https://github.com/laser-erp/Laser-ERP , ветка **main**.

---

## Шаги

### 1. Снимок «до»

```bash
systemctl is-active laser-erp nginx
curl -sS -o /dev/null -w "admin_login=%{http_code}\n" https://laser-erp.armada.sx/admin/login/
sudo -u lasererp bash -lc 'cd /var/www/laser-erp && git rev-parse --short HEAD'
```

Записать коммит «до» в отчёт.

### 2. Обновление кода и деплой

```bash
cd /var/www/laser-erp
sudo bash deploy/update_ubuntu.sh
```

Скрипт сам делает `git pull`, `pip install`, **migrate** с Postgres (через `POSTGRES_*` из `/etc/laser-erp.env`), `collectstatic`, `restart laser-erp`.

**Ожидаемые миграции** (если ещё не применены): `0133` … `0136` (`core`).

Если `update_ubuntu.sh` упал на migrate — **не** гонять `migrate` без env. Вручную только так:

```bash
source /etc/laser-erp.env
sudo -u lasererp env \
  DJANGO_SETTINGS_MODULE=laser_erp.settings_prod \
  POSTGRES_DB="$POSTGRES_DB" \
  POSTGRES_USER="$POSTGRES_USER" \
  POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}" \
  POSTGRES_PORT="${POSTGRES_PORT:-5432}" \
  /var/www/laser-erp/.venv/bin/python /var/www/laser-erp/manage.py migrate --noinput
sudo bash /var/www/laser-erp/deploy/update_ubuntu.sh
```

(или `collectstatic` + `systemctl restart laser-erp`, если pull уже был.)

### 3. Проверка миграций в Postgres

```bash
source /etc/laser-erp.env
sudo -u lasererp env \
  DJANGO_SETTINGS_MODULE=laser_erp.settings_prod \
  POSTGRES_DB="$POSTGRES_DB" \
  POSTGRES_USER="$POSTGRES_USER" \
  POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}" \
  POSTGRES_PORT="${POSTGRES_PORT:-5432}" \
  /var/www/laser-erp/.venv/bin/python /var/www/laser-erp/manage.py showmigrations core | tail -n 8
```

В отчёте: `[X]` у `0133`–`0136`.

### 4. Проверка сайта

```bash
curl -sS -o /dev/null -w "admin_login=%{http_code}\n" https://laser-erp.armada.sx/admin/login/
```

Опционально: открыть техкарту «Табличка Баня» (если есть на проде) — лазерная резка ~0,46 м, **без** строк гравировки.

### 5. Отчёт и GitHub

- Заполнить раздел **«Отчёт облачного агента»** ниже.
- Статус: `done` или `blocked`.
- **Сохранить в истории проекта и выложить на GitHub** (`current-task.md` с отчётом).

---

## Критерий «готово»

- [ ] `git rev-parse` на сервере = коммит с **main** после этого релиза.
- [ ] `0133`–`0136` применены в **Postgres** (не только SQLite).
- [ ] `/admin/login/` — **200** или **302**, не **500**.
- [ ] `laser-erp` и `nginx` — **active**.
- [ ] Отчёт заполнен и **на GitHub**.

---

## Отчёт облачного агента

### Дата и время

(заполнить)

### Git: коммит на сервере до / после

(заполнить)

### update_ubuntu.sh

(последние ~25 строк вывода или ошибка)

### showmigrations core (0133–0136)

(вставить строки)

### admin_login HTTP-код

(заполнить)

### Статус финальный

`waiting` → `done` / `blocked`

### Что нужно от владельца / локального агента

(если blocked)

---

*Конец задания.*
