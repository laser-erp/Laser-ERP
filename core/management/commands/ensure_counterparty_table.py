"""
Если миграция 0031 была помечена --fake, а таблицы в SQLite нет — создаёт её.
Использование: python manage.py ensure_counterparty_table
"""
import sqlite3

from django.conf import settings
from django.core.management.base import BaseCommand

SQL = """
CREATE TABLE IF NOT EXISTS "core_productionstagecounterpartyservice" (
  "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
  "organization_id" bigint NOT NULL REFERENCES "core_organization" ("id") DEFERRABLE INITIALLY DEFERRED,
  "production_stage_id" bigint NOT NULL REFERENCES "core_productionstage" ("id") DEFERRABLE INITIALLY DEFERRED,
  "service_id" bigint NULL REFERENCES "core_product" ("id") DEFERRABLE INITIALLY DEFERRED
);
CREATE UNIQUE INDEX IF NOT EXISTS "core_productionstagecounterpartyservice_production_stage_id_organization_id_38866e30_uniq"
  ON "core_productionstagecounterpartyservice" ("production_stage_id", "organization_id");
CREATE INDEX IF NOT EXISTS "core_productionstagecounterpartyservice_organization_id_991c3529"
  ON "core_productionstagecounterpartyservice" ("organization_id");
CREATE INDEX IF NOT EXISTS "core_productionstagecounterpartyservice_production_stage_id_0af15ce9"
  ON "core_productionstagecounterpartyservice" ("production_stage_id");
CREATE INDEX IF NOT EXISTS "core_productionstagecounterpartyservice_service_id_a8f9237e"
  ON "core_productionstagecounterpartyservice" ("service_id");
"""


class Command(BaseCommand):
    help = "Создаёт таблицу core_productionstagecounterpartyservice при отсутствии (после --fake миграции)."

    def handle(self, *args, **options):
        engine = settings.DATABASES["default"].get("ENGINE", "")
        if "sqlite" not in engine:
            self.stdout.write(
                self.style.WARNING(
                    "Команда рассчитана на SQLite. Для другой БД выполните: python manage.py migrate core"
                )
            )
            return
        path = settings.DATABASES["default"]["NAME"]
        conn = sqlite3.connect(str(path))
        try:
            conn.executescript(SQL)
            conn.commit()
        finally:
            conn.close()
        self.stdout.write(self.style.SUCCESS("Таблица core_productionstagecounterpartyservice проверена/создана."))
