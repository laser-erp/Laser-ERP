from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm

from .models import UserProfile


User = get_user_model()


class UserProfileForm(forms.ModelForm):
    first_name = forms.CharField(label="Имя", required=False)
    last_name = forms.CharField(label="Фамилия", required=False)
    email = forms.EmailField(label="E-mail")

    class Meta:
        model = UserProfile
        fields = ("avatar", "middle_name", "phone")
        labels = {
            "avatar": "Аватар",
            "middle_name": "Отчество",
            "phone": "Телефон",
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        self.fields["first_name"].initial = self.user.first_name
        self.fields["last_name"].initial = self.user.last_name
        self.fields["email"].initial = self.user.email
        self.fields["avatar"].required = False
        self.fields["middle_name"].required = False
        self.fields["phone"].required = False

        for field_name in ("first_name", "last_name", "email", "middle_name", "phone", "avatar"):
            widget = self.fields[field_name].widget
            css = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{css} form-control".strip()

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            raise forms.ValidationError("Укажите e-mail.")
        qs = User.objects.filter(email__iexact=email).exclude(pk=self.user.pk)
        if qs.exists():
            raise forms.ValidationError("Пользователь с таким e-mail уже существует.")
        return email

    def save(self, commit=True):
        profile = super().save(commit=False)
        self.user.first_name = (self.cleaned_data.get("first_name") or "").strip()
        self.user.last_name = (self.cleaned_data.get("last_name") or "").strip()
        self.user.email = self.cleaned_data["email"]
        if commit:
            self.user.save(update_fields=["first_name", "last_name", "email"])
            profile.user = self.user
            profile.save()
        return profile


class AccountPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css} form-control".strip()


