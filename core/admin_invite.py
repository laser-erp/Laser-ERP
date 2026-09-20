from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import AdminInvite


def email_smtp_ready() -> bool:
    host = (getattr(settings, "EMAIL_HOST", "") or "").strip()
    user = (getattr(settings, "EMAIL_HOST_USER", "") or "").strip()
    password = (getattr(settings, "EMAIL_HOST_PASSWORD", "") or "").strip()
    backend = (getattr(settings, "EMAIL_BACKEND", "") or "").strip()
    if backend.endswith("console.EmailBackend"):
        return True
    if not host or host.lower() in {"localhost", "127.0.0.1"}:
        return False
    return bool(user and password)


def public_site_base(request=None) -> str:
    if request is not None:
        return f"{request.scheme}://{request.get_host()}".rstrip("/")
    configured = (getattr(settings, "PUBLIC_SITE_URL", "") or "").strip().rstrip("/")
    if configured:
        return configured
    if getattr(settings, "DEBUG", False):
        return "http://127.0.0.1:8000"
    return "https://laser-erp.armada.sx"


def invite_accept_path(invite: AdminInvite) -> str:
    return reverse("account_admin_invite_accept", args=[invite.token])


def invite_accept_url(request, invite: AdminInvite) -> str:
    if request is not None:
        return request.build_absolute_uri(invite_accept_path(invite))
    return f"{public_site_base()}{invite_accept_path(invite)}"


def invite_link_html(invite: AdminInvite, request=None) -> str:
    if not invite or not invite.token:
        return "—"
    url = invite_accept_url(request, invite)
    return format_html('<a href="{0}" target="_blank" rel="noopener">{0}</a>', url)


def send_admin_invite_email(request, invite: AdminInvite, *, force: bool = False) -> str:
    """
    Опциональная отправка письма (если SMTP настроен).
    По умолчанию приглашения передаются ссылкой из админки.
    """
    if invite.accepted_at is not None:
        raise ValueError("Приглашение уже принято — письмо не нужно.")

    if invite.sent_at is not None and not force:
        return invite_accept_url(request, invite)

    accept_url = invite_accept_url(request, invite)

    if not email_smtp_ready():
        raise RuntimeError("SMTP не настроен — используйте ссылку из админки.")

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or settings.EMAIL_HOST_USER
    send_mail(
        "Приглашение в админку Laser ERP",
        (
            "Здравствуйте!\n\n"
            "Вам отправлено приглашение для доступа в админку Laser ERP.\n\n"
            f"Перейдите по ссылке, чтобы подтвердить email и задать пароль:\n{accept_url}\n\n"
            "Если это были не вы — просто проигнорируйте письмо."
        ),
        from_email,
        [invite.email],
        fail_silently=False,
    )

    invite.sent_at = timezone.now()
    invite.save(update_fields=["sent_at"])
    return accept_url
