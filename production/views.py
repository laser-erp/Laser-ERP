from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Sum
from django.shortcuts import render

from core.models import (
    ProductionAssignment,
    ProductionAssignmentItem,
    ProductionOrder,
    ProductionStage,
)


@staff_member_required
def production_status(request):
    """
    Статус производства: сводка по заказам и заданиям.
    """
    orders_by_status = (
        ProductionOrder.objects.values("status")
        .annotate(count=Count("id"))
        .order_by("status")
    )
    assignments_by_status = (
        ProductionAssignment.objects.values("status")
        .annotate(count=Count("id"))
        .order_by("status")
    )
    return render(
        request,
        "production/status.html",
        {
            "title": "Статус производства",
            "orders_by_status": list(orders_by_status),
            "assignments_by_status": list(assignments_by_status),
        },
    )


@staff_member_required
def stage_register(request):
    """
    Реестр выполнения этапов — список позиций производственных заданий
    с этапом, техкартой, статусом, браком и датами.
    """
    items = (
        ProductionAssignmentItem.objects.select_related(
            "assignment",
            "production_stage",
            "tech_card",
        )
        .annotate(defect_qty=Sum("defects__quantity"))
        .order_by("assignment", "sequence", "pk")
    )
    assignment_id = request.GET.get("assignment")
    if assignment_id:
        items = items.filter(assignment_id=assignment_id)
    stage_id = request.GET.get("stage")
    if stage_id:
        items = items.filter(production_stage_id=stage_id)
    status = request.GET.get("status")
    if status:
        items = items.filter(status=status)
    return render(
        request,
        "production/stage_register.html",
        {
            "items": items,
            "stages": ProductionStage.objects.all().order_by("sequence", "name"),
            "title": "Реестр выполнения этапов",
        },
    )
