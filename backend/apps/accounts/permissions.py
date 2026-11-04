from rest_framework.permissions import BasePermission


class HasRestaurant(BasePermission):
    message = "No active restaurant for this user."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and getattr(request, "restaurant", None))


def require(perm):
    """DRF permission factory: ``permission_classes = [require('menu')]``."""

    class _Perm(BasePermission):
        message = f"Missing permission: {perm}"

        def has_permission(self, request, view):
            m = getattr(request, "membership", None)
            return bool(getattr(request, "restaurant", None) and m and m.can(perm))

    _Perm.__name__ = f"Require_{perm}"
    return _Perm
