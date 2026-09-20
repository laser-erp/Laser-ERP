from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0132_production_request_order_mode_quote"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PasswordResetRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("short_code", models.CharField(db_index=True, max_length=16, verbose_name="Код для администратора")),
                ("expires_at", models.DateTimeField(verbose_name="Действует до")),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True, verbose_name="IP запроса")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создан")),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="password_reset_requests",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Запрос сброса пароля",
                "verbose_name_plural": "Запросы сброса пароля",
                "ordering": ("-created_at",),
                "indexes": [models.Index(fields=["short_code", "expires_at"], name="core_passwo_short_c_6f0a8d_idx")],
            },
        ),
    ]
