from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from .models import AdminInvite


def send_admin_invite_email(request, invite: AdminInvite) -> str:
    """
    Отправляет письмо с приглашением в админку.
    Возвращает URL, на который ссылается письмо.
    """
    if invite.sent_at is not None or invite.accepted_at is not None:
        # Повторная отправка не нужна.
        return ""

    accept_url = request.build_absolute_uri(
        reverse("account_admin_invite_accept", args=[invite.token])
    )

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@laser-erp.local")
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
        fail_silently=True,
    )

    invite.sent_at = timezone.now()
    invite.save(update_fields=["sent_at"])
    return accept_url

