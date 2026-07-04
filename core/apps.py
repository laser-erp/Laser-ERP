from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Основные данные"

    def ready(self) -> None:
        from core.admin_numeric_locale import patch_admin_numeric_locale

        patch_admin_numeric_locale()
