from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm

User = get_user_model()


class UsernamePasswordResetRequestForm(forms.Form):
    """Сброс без почты: пользователь указывает логин, админ выдаёт ссылку по коду."""

    username = forms.CharField(
        label="Логин",
        max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "username", "class": "vTextField"}),
    )

    def clean_username(self):
        return (self.cleaned_data.get("username") or "").strip()

    def resolve_user(self):
        username = self.cleaned_data.get("username")
        if not username:
            return None
        return User.objects.filter(username__iexact=username, is_active=True).first()


class LaserPasswordResetForm(PasswordResetForm):
    """Email-сброс с русской подписью поля."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].label = "Email"
