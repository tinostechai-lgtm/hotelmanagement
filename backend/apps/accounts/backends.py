"""Log in with a mobile number *or* an email address in the same field."""
import re

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


def normalize_phone(value):
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits


def find_users(identifier):
    """Candidate accounts for a login identifier (email or mobile)."""
    User = get_user_model()
    identifier = (identifier or "").strip()
    if not identifier:
        return User.objects.none()
    if "@" in identifier:
        return User.objects.filter(email__iexact=identifier)
    phone = normalize_phone(identifier)
    candidates = {identifier, phone, f"+91{phone}", f"91{phone}"} - {""}
    return User.objects.filter(username__in=candidates)


class EmailOrPhoneBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        for user in find_users(username):
            if user.check_password(password) and self.user_can_authenticate(user):
                return user
        # Run the hasher once anyway so timing doesn't reveal whether the account exists.
        get_user_model()().set_password(password)
        return None
