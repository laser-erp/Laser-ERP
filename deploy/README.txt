Laser ERP — развёртывание на Ubuntu
====================================

БЫСТРЫЙ СТАРТ (на чистом Ubuntu 22.04/24.04)
--------------------------------------------
1. sudo bash deploy/install_ubuntu.sh
2. sudo nano /etc/laser-erp.env   — SECRET_KEY, домен, пароль PostgreSQL
3. sudo systemctl restart laser-erp
4. cd /var/www/laser-erp && sudo -u lasererp .venv/bin/python manage.py createsuperuser

Перенос данных с Windows
--------------------------
На Windows:
  python tools/export_data.py
  (скопировать бекапы/data_export_*.json и папку media/ на сервер)

На сервере:
  sudo -u lasererp .venv/bin/python manage.py loaddata /path/to/data_export.json

Обновление после git push
-------------------------
  sudo bash deploy/update_ubuntu.sh

Автозапуск и бэкапы
-------------------
  systemctl status laser-erp     — приложение
  systemctl status nginx         — веб-сервер
  cron: deploy/cron/laser-erp-backup → tools/backup_server.py (ежедневно 03:15)

HTTPS
-----
  sudo apt install certbot python3-certbot-nginx
  sudo certbot --nginx -d ваш-домен.ru

Файлы
-----
  deploy/env.example          — шаблон /etc/laser-erp.env
  deploy/systemd/laser-erp.service
  deploy/nginx/laser-erp.conf
  laser_erp/settings_prod.py  — боевые настройки Django
