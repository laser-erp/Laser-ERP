from django import template
from django.contrib.admin.templatetags.admin_list import search_form

register = template.Library()


@register.inclusion_tag("admin/warehouse/search_form.html")
def warehouse_search_form(cl):
    """Тот же контекст, что у {% search_form cl %}, но свой шаблон (плейсхолдер и разметка под toolbar)."""
    return search_form(cl)
