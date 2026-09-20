# Задание для облачного агента (сервер)

**Обновлено локальным агентом:** 2026-09-20  
**Фаза плана:** 0.1 + 0.2 — [erp_launch_strategy_and_roadmap.md](../../plans/erp_launch_strategy_and_roadmap.md)

---

## Статус

| Поле | Значение |
|------|----------|
| **Статус** | `waiting` |
| **Кто выполняет** | cloud-agent |
| **Блокер** | — |

*(Облачный агент: при старте поставьте `in_progress`, по завершении — `done` или `blocked`.)*

---

## Цель

1. Подтянуть на VPS **последний код** с GitHub (ветка **main**).
2. **Применить миграции базы** (в т.ч. `core` **0131**, **0132**).
3. Пересобрать статику и **перезапустить** сайт.
4. Проверить, что https://laser-erp.armada.sx/admin/login/ отвечает без ошибки 500.
5. Кратко проверить почту (переменные `EMAIL_*` в `/etc/laser-erp.env`) — **значения не копировать в отчёт**.

---

## Предусловия

- SSH к `176.12.66.161` (секреты — см. [README.md](./README.md)).
- Не запускать `tools/_deploy_server.py` (затирает каталог и делает loaddata).
- Предпочтительно: `deploy/update_ubuntu.sh` из `/var/www/laser-erp`.

---

## Шаги

### 1. Подключение и снимок «до»

```bash
ssh -p "${SSH_PORT:-22}" "${SSH_USER}@${SSH_HOST}"
systemctl is-active laser-erp nginx
cd /var/www/laser-erp && sudo -u lasererp git remote -v && sudo -u lasererp git rev-parse --short HEAD
```

Зафиксировать в отчёте: активны ли сервисы, какой коммит **до** обновления.

### 2. Обновление приложения

```bash
cd /var/www/laser-erp
sudo bash deploy/update_ubuntu.sh
```

Если скрипт падает на `git pull` — в отчёте **точный текст ошибки**; статус `blocked`.

### 3. Проверка миграций

```bash
set -a && source /etc/laser-erp.env && set +a
cd /var/www/laser-erp
sudo -u lasererp env \
  DJANGO_SETTINGS_MODULE=laser_erp.settings_prod \
  POSTGRES_DB="$POSTGRES_DB" POSTGRES_USER="$POSTGRES_USER" \
  POSTGRES_PASSWORD="$POSTGRES_PASSWORD" POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}" \
  POSTGRES_PORT="${POSTGRES_PORT:-5432}" \
  .venv/bin/python manage.py showmigrations core | tail -n 8
```

В отчёте: применены ли **0131_user_action_log** и **0132_production_request_order_mode_quote** (отметка `[X]`).

### 4. Проверка сайта с сервера

```bash
curl -sS -o /dev/null -w "admin_login_http=%{http_code}\n" \
  -H "Host: laser-erp.armada.sx" \
  https://127.0.0.1/admin/login/ -k || \
curl -sS -o /dev/null -w "admin_login_http=%{http_code}\n" \
  -H "Host: laser-erp.armada.sx" \
  http://127.0.0.1:8001/admin/login/
```

Ожидаемо: **200** или **302** (не **500**).

### 5. Admin (без пароля в Git)

```bash
# только список логинов суперпользователей, без сброса пароля
set -a && source /etc/laser-erp.env && set +a
cd /var/www/laser-erp
sudo -u lasererp env \
  DJANGO_SETTINGS_MODULE=laser_erp.settings_prod \
  POSTGRES_DB="$POSTGRES_DB" POSTGRES_USER="$POSTGRES_USER" \
  POSTGRES_PASSWORD="$POSTGRES_PASSWORD" POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}" \
  POSTGRES_PORT="${POSTGRES_PORT:-5432}" \
  .venv/bin/python manage.py shell -c \
  "from django.contrib.auth.models import User; print(list(User.objects.filter(is_superuser=True).values_list('username', flat=True)))"
```

**Сброс пароля Admin** — только если владелец **явно написал** облачному агенту в чате; новый пароль **не писать в этот файл**, передать владельцу **только в чате Cursor**.

### 6. Почта (без секретов)

```bash
grep -E '^EMAIL_|^DEFAULT_FROM' /etc/laser-erp.env | sed 's/PASSWORD=.*/PASSWORD=***/'
```

В отчёте: задан ли `EMAIL_HOST`, пустой ли пароль (да/нет).

---

## Критерий «готово»

- [ ] `update_ubuntu.sh` успешен (или описана блокировка).
- [ ] Миграции 0131–0132 применены.
- [ ] `/admin/login/` не отдаёт 500.
- [ ] Отчёт ниже заполнен и **выложен на GitHub**.

---

## Отчёт облачного агента

*(Заполняет только облачный агент. Без паролей.)*

### Дата и время (UTC или MSK)

### Коммит на сервере после обновления

### Результаты шагов 1–6

### Ошибки / хвост логов (если были)

```text
(вставить последние строки django_errors.log или gunicorn_error.log при 500)
```

### Статус финальный

`done` | `blocked` — …

### Что нужно от локального агента / владельца

---

*Конец задания.*
