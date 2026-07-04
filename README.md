# Laser ERP

Локальная ERP-система для учета заказов, закупок, склада, производства и расходов лазерного производства.

## Быстрый старт

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Админка: `http://127.0.0.1:8000/admin/`

## Переменные окружения

- `DJANGO_SECRET_KEY` — секретный ключ Django для боевого/удаленного окружения.
- `FNS_API_KEY` — ключ API-ФНС для поиска и обновления контрагентов.
- `BANK_PAYMENT_API_URL` и `BANK_PAYMENT_API_TOKEN` — настройки интеграции с банком.

Локальные файлы базы, медиа, бэкапы, логи и `.venv` не хранятся в репозитории.

