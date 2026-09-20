# Инструкция для Cloud Agent — Laser ERP (прод)

Документ для **нового агента**, продолжающего работу с production без истории чата.

## Цель и текущий статус

| Задача | Статус |
|--------|--------|
| Доступ в Django-админку на проде | Сделано (суперпользователь `admin`, пароль менялся вручную — **не хранить в git**) |
| SSH-ключ агента на VPS | Сделано: публичный ключ `laser-erp-agent` в `/root/.ssh/authorized_keys` (блок `# CURSOR-AGENT-SSH-*`) |
| Сброс пароля **без почты** (логин → код → админ) | На проде: `PASSWORD_RESET_EMAIL_ENABLED=0` |
| Сброс пароля **по email** (Яндекс) | **Не завершено**: host/user Яндекса на сервере есть, `EMAIL_HOST_PASSWORD` ещё не пароль приложения |
| Код сброса пароля | На проде уже через `rsync`; в git — PR https://github.com/laser-erp/Laser-ERP/pull/1 и ветка `cursor/yandex-smtp-vps-58a2` |

Проверка 2026-09-20 (агент `Laser ERP VPS smtp`):

- Секреты **есть:** `VPS_HOST`, `VPS_USER`, `VPS_PASSWORD`, `VPS_SSH_PRIVATE_KEY` (OpenSSH PEM, иногда в одну строку **с пробелами** вместо переводов строк).
- Секреты **нет:** `YANDEX_SMTP_PASSWORD`, `YANDEX_SMTP_USER`.
- SSH по `~/.ssh/vps_key` работает после `python3 tools/install_vps_ssh_key.py`.
- `send_mail` на проде: `SMTPAuthenticationError` 535 (`smtp.yandex.ru` / `Armada.sx@yandex.ru`, текущий `EMAIL_HOST_PASSWORD` короткий и не принимается).
- https://laser-erp.armada.sx/admin/password_reset/ — поле **логин**, почта не используется.

---

## Секреты Cursor (обязательно проверить в начале)

Должны быть в **Secrets** Cloud Agent (тот же список, что `VPS_PASSWORD`):

| Секрет | Назначение |
|--------|------------|
| `VPS_HOST` | Хост VPS (значение в Secrets, не в git) |
| `VPS_USER` | `root` |
| `VPS_PASSWORD` | Пароль root (запасной вход, если ключ не сработал) |
| `VPS_SSH_PRIVATE_KEY` | **Полный** OpenSSH PEM (`BEGIN OPENSSH PRIVATE KEY`), не пароль root |
| `YANDEX_SMTP_PASSWORD` | Пароль приложения Яндекса для `Armada.sx@yandex.ru` |
| `YANDEX_SMTP_USER` | Опционально; по умолчанию `Armada.sx@yandex.ru` |

**Проверка без утечки:**

```bash
python3 -c "
import os
for k in ('VPS_HOST','VPS_USER','VPS_PASSWORD','VPS_SSH_PRIVATE_KEY','YANDEX_SMTP_PASSWORD','YANDEX_SMTP_USER'):
    v=os.environ.get(k,'')
    print(k, 'set=', bool(v), 'len=', len(v), 'openssh=', 'BEGIN' in v if k=='VPS_SSH_PRIVATE_KEY' else '-')
"
```

Если `YANDEX_SMTP_PASSWORD` **не set** — SMTP на сервере не завершить. Попросить добавить секрет (пароль приложения Яндекса, без пробелов). Не печатать значение.

Секрет, добавленный через форму Cloud Agent **в уже запущенный** агент, в этот VM часто **не попадает** (`CLOUD_AGENT_ALL_SECRET_NAMES` остаётся прежним). Нужен **новый** Cloud Agent после сохранения секрета. Этот запуск был без linked Environment — секреты должны быть в том же списке, что `VPS_PASSWORD`, либо агент надо стартовать с Environment, куда секрет записали.

`VPS_SSH_PRIVATE_KEY` часто приходит **одной строкой с пробелами** вокруг base64. Не писать его в файл как есть — только через `tools/install_vps_ssh_key.py`.

---

## Подключение к VPS

```bash
python3 tools/install_vps_ssh_key.py
ssh -i ~/.ssh/vps_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new root@${VPS_HOST}
```

Запасной вариант: `sshpass` + `VPS_PASSWORD` (как в `tools/setup_home_ssh_tunnel.py`).

**Прод:**

- Приложение: `/var/www/laser-erp`
- Пользователь сервиса: `lasererp`
- venv: `/var/www/laser-erp/.venv`
- Env: `/etc/laser-erp.env` (секреты, **не коммитить**)
- Systemd: `laser-erp.service` → gunicorn `127.0.0.1:8001`
- Сайт: https://laser-erp.armada.sx/admin/

**Важно:** на сервере **нет git-репозитория** — деплой делался `rsync` с агента. После merge PR можно снова `rsync` или настроить git на VPS.

---

## Django / БД на проде

- `manage.py` **без** `source /etc/laser-erp.env` попадёт в SQLite и устаревшую схему.
- Всегда для prod-команд:

```bash
set -a && source /etc/laser-erp.env && set +a
cd /var/www/laser-erp
sudo -E -u lasererp .venv/bin/python manage.py shell -c '...'
```

- БД: **PostgreSQL** (`POSTGRES_*` в env).
- Миграция сброса без почты: `core.0133_password_reset_request` (должна быть применена).

---

## Сброс пароля: два режима

Управляется `PASSWORD_RESET_EMAIL_ENABLED` в `/etc/laser-erp.env` (и логикой `laser_erp/mail.py` + `core/services/password_reset.py`).

### A. Без почты (`PASSWORD_RESET_EMAIL_ENABLED=0`) — **сейчас на проде**

1. Пользователь: https://laser-erp.armada.sx/admin/password_reset/ → **логин** → получает **код**.
2. Админ: админка → **«Запросы сброса пароля»** → ссылка по коду **или** «Пользователи» → действие **«Сгенерировать ссылку сброса пароля»**.
3. Подтверждение: `/reset/<uid>/<token>/` → новый пароль.

### B. По email (`PASSWORD_RESET_EMAIL_ENABLED=1`)

1. Рабочий SMTP (см. ниже).
2. У пользователя в Django указан **реальный email** (не `admin@example.com`).
3. Форма сброса просит **email**, письмо со ссылкой `/reset/...`.

**Почему не Mail.ru / biz для `LC@armada.sx`:** SMTP даёт 535 — нужен платный пароль приложения. Используется **Яндекс** `Armada.sx@yandex.ru`.

---

## Донастройка Яндекс SMTP (главная незавершённая задача)

### Текущее содержимое `/etc/laser-erp.env` (ожидаемое)

```env
EMAIL_HOST=smtp.yandex.ru
EMAIL_PORT=465
EMAIL_USE_SSL=1
EMAIL_USE_TLS=0
EMAIL_HOST_USER=Armada.sx@yandex.ru
DEFAULT_FROM_EMAIL=Armada.sx@yandex.ru
SERVER_DOMAIN=laser-erp.armada.sx
PASSWORD_RESET_EMAIL_ENABLED=0
EMAIL_HOST_PASSWORD=<старый короткий пароль — ЗАМЕНИТЬ на пароль приложения Яндекса>
```

Не включать `PASSWORD_RESET_EMAIL_ENABLED=1`, пока `send_mail` не вернул `SENT`. Иначе форма сброса уйдёт в SMTP и даст 500.

### Шаги агента

1. Убедиться, что `YANDEX_SMTP_PASSWORD` есть в env агента.
2. Записать ключ: `python3 tools/install_vps_ssh_key.py`.
3. Из корня репозитория:

```bash
pip install paramiko  # если нет
python3 tools/apply_yandex_smtp_to_vps.py
```

Скрипт обновляет `/etc/laser-erp.env`, ставит `PASSWORD_RESET_EMAIL_ENABLED=1`, перезапускает `laser-erp`, шлёт тестовое письмо на `DEFAULT_FROM_EMAIL`. Пробелы в пароле приложения снимаются.

4. Если скрипт вернул `exit=2` — секрет не инжектнут; не продолжать вслепую.

**Ручная альтернатива на VPS** (не печатать пароль в лог):

```bash
ssh -i ~/.ssh/vps_key root@${VPS_HOST}
nano /etc/laser-erp.env   # EMAIL_HOST_PASSWORD=пароль_приложения_яндекса
# PASSWORD_RESET_EMAIL_ENABLED=1
systemctl restart laser-erp
```

5. Тест с сервера:

```bash
set -a && source /etc/laser-erp.env && set +a
cd /var/www/laser-erp
sudo -E -u lasererp .venv/bin/python manage.py shell -c "
from django.core.mail import send_mail
from django.conf import settings
send_mail('Test','OK',settings.DEFAULT_FROM_EMAIL,[settings.DEFAULT_FROM_EMAIL],fail_silently=False)
print('ok')
"
```

6. E2E снаружи: GET `/admin/password_reset/` → поле **Email** → POST → письмо → `/reset/...` → вход в админку.

### Суперпользователи и email (проверено 2026-09-20)

| username | email |
|----------|--------|
| `admin` | `admin@example.com` (на этот адрес письмо не придёт) |
| `Admin` | `LC@armada.sx` |
| `faktoryal` | `faktoryal@yandex.ru` |

У `admin` при необходимости сменить email в админке на рабочий.

---

## Восстановление, если все админы забыли пароль

Без почты и без второго админа — только **SSH**:

```bash
cd /var/www/laser-erp && source /etc/laser-erp.env
sudo -E -u lasererp .venv/bin/python manage.py changepassword Admin
```

---

## Деплой изменений кода

```bash
export RSYNC_RSH="ssh -i ~/.ssh/vps_key -o IdentitiesOnly=yes"
rsync -az \
  --exclude '.git' --exclude '.venv' --exclude '__pycache__' --exclude 'media' \
  --exclude 'staticfiles' --exclude 'db.sqlite3' --exclude 'logs' --exclude '.env.server' \
  /workspace/ root@${VPS_HOST}:/var/www/laser-erp/
ssh -i ~/.ssh/vps_key root@${VPS_HOST} 'chown -R lasererp:www-data /var/www/laser-erp && bash /var/www/laser-erp/deploy/update_ubuntu.sh'
```

Если `git pull` в `update_ubuntu.sh` падает — на VPS нет git; использовать только rsync.

**Миграции:** на проде могут быть файлы `0131`, `0132`, которых нет на `main` — не удалять. Новые миграции — с зависимостью от последней на сервере (`0132` → `0133`).

---

## Чего не делать

- Не коммитить `/etc/laser-erp.env`, пароли, приватные ключи, пароли админки.
- Не светить `VPS_SSH_PRIVATE_KEY`, `YANDEX_SMTP_PASSWORD`, `EMAIL_HOST_PASSWORD` в чат и логи.
- Не подставлять root-пароль в `VPS_SSH_PRIVATE_KEY`.
- Не полагаться на biz.mail.ru для `LC@armada.sx` без пароля приложения.

---

## Полезные файлы в репозитории

| Файл | Содержание |
|------|------------|
| `laser_erp/mail.py` | SMTP и `PASSWORD_RESET_EMAIL_ENABLED` |
| `core/services/password_reset.py` | Ссылки сброса, режим email/offline |
| `core/views_password_reset.py` | Формы сброса |
| `core/admin_users.py` | Запросы сброса, action у User |
| `tools/install_vps_ssh_key.py` | PEM из `VPS_SSH_PRIVATE_KEY` → `~/.ssh/vps_key` |
| `tools/apply_yandex_smtp_to_vps.py` | Применить Яндекс SMTP на VPS |
| `deploy/env.example` | Шаблон env |

---

## Краткий чеклист для нового агента

1. [ ] Проверить секреты (`VPS_*`, `YANDEX_SMTP_PASSWORD`).
2. [ ] `python3 tools/install_vps_ssh_key.py` и SSH на VPS по ключу.
3. [ ] При наличии `YANDEX_SMTP_PASSWORD` — `python3 tools/apply_yandex_smtp_to_vps.py`.
4. [ ] Проверить тестовое письмо и `/admin/password_reset/` (поле Email).
5. [ ] Сообщить пользователю результат **без** паролей и ключей.
6. [ ] Обновить PR при изменениях в коде; на прод код уже частично залит через rsync.
