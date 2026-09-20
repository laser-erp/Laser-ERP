"""Запись ключевых действий пользователя в журнал."""

from .models import UserActionLog


def log_user_action(user, action, *, detail="", related_employee=None):
    if not user or not getattr(user, "is_authenticated", False):
        return None
    return UserActionLog.objects.create(
        user=user,
        action=action,
        detail=(detail or "")[:2000],
        related_employee=related_employee,
    )
