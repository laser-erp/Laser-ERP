"""
Кастомный ChangeList для техкарт: ?tc_product= без ошибки lookup; фильтрация в get_queryset.
"""
from collections import defaultdict
from decimal import Decimal

from django.contrib.admin.views.main import ChangeList
from django.db.models import Count

from core.models import Product, ProductGroup, TechCard


class TechCardChangelist(ChangeList):
    def get_filters_params(self, params=None):
        lookup_params = super().get_filters_params(params)
        if "tc_product" not in lookup_params:
            return lookup_params
        return {k: v for k, v in lookup_params.items() if k != "tc_product"}

    def get_queryset(self, request, exclude_parameters=None):
        tc = request.GET.get("tc_product")
        qs = super().get_queryset(request, exclude_parameters=exclude_parameters)
        if not tc:
            return qs
        if tc == "_none_":
            return qs.filter(product__isnull=True)
        try:
            return qs.filter(product_id=int(tc))
        except ValueError:
            return qs


def build_techcard_sidebar_tree():
    """Группа товаров → изделия с техкартами."""
    pids = (
        TechCard.objects.filter(product_id__isnull=False)
        .values("product_id")
        .annotate(n=Count("id"))
        .filter(n__gte=1)
        .values_list("product_id", flat=True)
    )
    pids = list(pids)
    if not pids:
        return {
            "groups": [],
            "has_orphans": TechCard.objects.filter(product__isnull=True).exists(),
            "orphan_count": TechCard.objects.filter(product__isnull=True).count(),
        }

    tc_counts = dict(
        TechCard.objects.filter(product_id__in=pids)
        .values("product_id")
        .annotate(n=Count("id"))
        .values_list("product_id", "n")
    )

    products = Product.objects.filter(pk__in=pids).select_related("product_group").order_by("name")

    by_group = defaultdict(list)
    for p in products:
        by_group[p.product_group_id].append(
            {"id": p.pk, "name": p.name, "count": tc_counts.get(p.pk, 0)}
        )

    groups_out = []
    for g in ProductGroup.objects.order_by("name"):
        children = by_group.get(g.pk) or []
        if children:
            groups_out.append({"id": g.pk, "name": g.name, "products": children})

    ungrouped = by_group.get(None) or []
    if ungrouped:
        groups_out.append({"id": None, "name": "Без группы", "products": ungrouped})

    orphan_count = TechCard.objects.filter(product__isnull=True).count()

    return {
        "groups": groups_out,
        "has_orphans": orphan_count > 0,
        "orphan_count": orphan_count,
    }


def tech_card_material_cost_estimate(tech_card) -> Decimal:
    """Оценка по позициям техкарты: цена материала — средневзвешенная по поступлениям (Material.average_price)."""
    return tech_card.planned_material_cost_per_unit()


def tech_card_cut_cost_estimate(tech_card) -> Decimal:
    """План по резу: норма м на изделие × ₽/м этапа по строкам техкарты."""
    return tech_card.planned_cut_cost_per_unit()
