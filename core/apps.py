from django.apps import AppConfig


def _patch_admin_file_widget() -> None:
    from django.contrib.admin.widgets import AdminFileWidget
    from django.forms.widgets import FileInput

    extra_classes = "file-upload-input laser-file-input-native"

    def _wrap_build_attrs(cls):
        if getattr(cls.build_attrs, "_laser_file_ru", False):
            return
        original = cls.build_attrs

        def build_attrs(self, base_attrs, extra_attrs=None):
            attrs = original(self, base_attrs, extra_attrs)
            css = attrs.get("class", "")
            missing = [cls_name for cls_name in extra_classes.split() if cls_name not in css.split()]
            if missing:
                attrs["class"] = f"{css} {' '.join(missing)}".strip()
            return attrs

        build_attrs._laser_file_ru = True
        cls.build_attrs = build_attrs

    _wrap_build_attrs(FileInput)
    _wrap_build_attrs(AdminFileWidget)


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Основные данные"

    def ready(self) -> None:
        from core.admin_numeric_locale import patch_admin_numeric_locale

        patch_admin_numeric_locale()
        _patch_admin_file_widget()
