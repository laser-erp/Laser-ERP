from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone
from uuid import uuid4

from .models import EmailVerification


def is_email_verified(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_staff or user.is_superuser:
        return True
    state = EmailVerification.objects.filter(user_id=user.pk).only("is_verified").first()
    if state is None:
        # Legacy users created before email verification rollout.
        return True
    return bool(state.is_verified)


def issue_email_verification(request, user) -> str:
    verification, _created = EmailVerification.objects.get_or_create(
        user=user,
        defaults={"is_verified": False},
    )
    verification.is_verified = False
    verification.verified_at = None
    verification.sent_at = timezone.now()
    verification.token = verification.token or uuid4().hex
    verification.save(update_fields=["is_verified", "verified_at", "sent_at", "token", "updated_at"])

    verification_url = request.build_absolute_uri(
        reverse("account_verify_email", args=[verification.token]),
    )
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@laser-erp.local")
    send_mail(
        "Подтверждение email в Laser ERP",
        (
            "Здравствуйте!\n\n"
            "Для активации вкладки 'Заказ на производство' подтвердите email по ссылке:\n"
            f"{verification_url}\n\n"
            "Если это были не вы, просто проигнорируйте письмо."
        ),
        from_email,
        [user.email],
        fail_silently=True,
    )
    return verification_url
