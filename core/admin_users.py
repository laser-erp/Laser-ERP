from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.html import format_html

from core.models import PasswordResetRequest
from core.services.password_reset import build_password_reset_public_url, build_password_reset_url


@admin.action(description="Сгенерировать ссылку сброса пароля")
def generate_password_reset_link(modeladmin, request, queryset):
    for user in queryset:
        if not user.is_active:
            modeladmin.message_user(
                request,
                f"{user.username}: учётная запись неактивна.",
                level=messages.WARNING,
            )
            continue
        url = build_password_reset_url(request, user)
        modeladmin.message_user(
            request,
            format_html("Ссылка для <strong>{}</strong>: <code>{}</code>", user.username, url),
            level=messages.SUCCESS,
        )


class LaserUserAdmin(DjangoUserAdmin):
    actions = list(DjangoUserAdmin.actions or []) + [generate_password_reset_link]


@admin.register(PasswordResetRequest)
class PasswordResetRequestAdmin(admin.ModelAdmin):
    list_display = (
        "short_code",
        "user",
        "is_active_display",
        "expires_at",
        "created_at",
        "ip_address",
    )
    list_filter = ("created_at",)
    search_fields = ("short_code", "user__username", "user__email")
    readonly_fields = (
        "user",
        "short_code",
        "expires_at",
        "ip_address",
        "created_at",
        "reset_link_display",
    )
    fields = readonly_fields

    @admin.display(boolean=True, description="Активен")
    def is_active_display(self, obj: PasswordResetRequest) -> bool:
        return obj.is_active

    @admin.display(description="Ссылка сброса")
    def reset_link_display(self, obj: PasswordResetRequest) -> str:
        if not obj.is_active:
            return "Срок действия истёк — создайте новый запрос или сгенерируйте ссылку у пользователя."
        url = build_password_reset_public_url(obj.user)
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', url, url)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return True


def register_user_admin() -> None:
    if admin.site.is_registered(User):
        admin.site.unregister(User)
    admin.site.register(User, LaserUserAdmin)
