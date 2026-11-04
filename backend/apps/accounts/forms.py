from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm


class PhoneOrEmailResetForm(PasswordResetForm):
    """Reset by registered mobile number or email; mail goes to the account's email."""

    email = forms.CharField(label="Mobile number or email", max_length=254)

    def get_users(self, value):
        value = value.strip()
        users = get_user_model()._default_manager.filter(is_active=True)
        users = users.filter(email__iexact=value) if "@" in value else users.filter(username=value)
        return (u for u in users if u.has_usable_password() and u.email)
