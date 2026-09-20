from .models import Employee

ROLE_CLIENT = "client"
ROLE_EMPLOYEE = "employee"
ROLE_EMPLOYEE_ADMIN = "employee_admin"
ROLE_PREVIEW_SESSION_KEY = "storefront_preview_role"
IMPERSONATE_EMPLOYEE_SESSION_KEY = "workspace_impersonate_employee_id"
ALLOWED_PREVIEW_ROLES = {ROLE_CLIENT, ROLE_EMPLOYEE, ROLE_EMPLOYEE_ADMIN}


def get_base_role(user):
    if not user or not user.is_authenticated:
        return ROLE_CLIENT

    employee = (
        Employee.objects.filter(user_id=user.pk)
        .only("position")
        .first()
    )
    if not employee:
        return ROLE_CLIENT

    is_admin_position = "администратор" in (employee.position or "").lower()
    if is_admin_position or user.is_staff or user.is_superuser:
        return ROLE_EMPLOYEE_ADMIN
    return ROLE_EMPLOYEE


def can_preview_roles(user):
    return get_base_role(user) == ROLE_EMPLOYEE_ADMIN


def can_impersonate_employees(user):
    """Замещение сотрудника — только у реальной роли employee_admin (не у preview)."""
    return get_base_role(user) == ROLE_EMPLOYEE_ADMIN


def get_impersonated_employee(request):
    user = getattr(request, "user", None)
    if not can_impersonate_employees(user):
        return None
    emp_id = request.session.get(IMPERSONATE_EMPLOYEE_SESSION_KEY)
    if not emp_id:
        return None
    try:
        emp_id = int(emp_id)
    except (TypeError, ValueError):
        return None
    return Employee.objects.filter(pk=emp_id).first()


def clear_impersonation(request):
    request.session.pop(IMPERSONATE_EMPLOYEE_SESSION_KEY, None)


def get_effective_role(request):
    user = getattr(request, "user", None)
    base_role = get_base_role(user)
    if base_role != ROLE_EMPLOYEE_ADMIN:
        return base_role

    preview = request.session.get(ROLE_PREVIEW_SESSION_KEY)
    if preview in ALLOWED_PREVIEW_ROLES:
        return preview
    return base_role
