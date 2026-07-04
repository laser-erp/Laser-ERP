"""
Единое отображение десятичного разделителя в админке (ru: запятая).

По умолчанию Django для Decimal/Float даёт NumberInput (в значении чаще точка),
а только для чтения числа показывает через localize — с запятой. Патч
включает localize для числовых полей формы (текстовый ввод по правилам ru).
"""
from __future__ import annotations

from django.contrib.admin.options import BaseModelAdmin
from django.db import models

_original_formfield_for_dbfield = BaseModelAdmin.formfield_for_dbfield


def _laser_formfield_for_dbfield(self, db_field, request, **kwargs):
    if not getattr(db_field, "primary_key", False):
        if isinstance(db_field, (models.DecimalField, models.FloatField)):
            kwargs["localize"] = True
        elif isinstance(db_field, models.IntegerField):
            kwargs["localize"] = True
    return _original_formfield_for_dbfield(self, db_field, request, **kwargs)


def patch_admin_numeric_locale() -> None:
    BaseModelAdmin.formfield_for_dbfield = _laser_formfield_for_dbfield
