"""Виджеты форм (админка и др.)."""

from django import forms
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

# Частые ед. изм.; значения согласованы с Product.normalized_uom_kind()
PRODUCT_UNIT_SUGGESTIONS = (
    "шт",
    "м",
    "м²",
    "кв. м",
    "п.м",
    "пог. м",
    "л.м",
    "кг",
    "т",
    "м³",
    "л",
    "компл",
    "упак",
    "мм",
    "см",
)


class UnitDatalistTextWidget(forms.TextInput):
    """
    Текстовое поле с выпадающим списком подсказок (HTML datalist).
    Можно выбрать вариант из списка или ввести любой текст — как раньше CharField.
    """

    def __init__(self, suggestions=PRODUCT_UNIT_SUGGESTIONS, attrs=None):
        self.suggestions = tuple(suggestions)
        super().__init__(attrs)

    def render(self, name, value, attrs=None, renderer=None):
        attrs = {**(attrs or {})}
        widget_id = attrs.get("id", f"id_{name}")
        datalist_id = f"{widget_id}_unit_datalist"
        attrs["list"] = datalist_id
        input_html = super().render(name, value, attrs, renderer)
        options = format_html_join(
            "",
            "<option value=\"{}\"></option>",
            ((s,) for s in self.suggestions),
        )
        datalist = format_html('<datalist id="{}">{}</datalist>', datalist_id, options)
        return mark_safe(input_html + datalist)
