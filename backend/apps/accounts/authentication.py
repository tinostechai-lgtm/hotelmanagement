"""JWT auth that keeps each crew login on one phone at a time."""
from rest_framework import exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication


MESSAGE = "This login is now in use on another phone. Each crew member needs their own login - ask your manager."


class OneDeviceJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        device = (request.headers.get("X-Device-Id") or "")[:64]
        if device and user.active_device and user.active_device != device and user.is_crew:
            raise exceptions.AuthenticationFailed({"detail": MESSAGE, "code": "signed_in_elsewhere"})
        return result
