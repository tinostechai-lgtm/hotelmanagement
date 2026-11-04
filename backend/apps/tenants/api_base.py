from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from apps.accounts.permissions import HasRestaurant
from apps.tenants.middleware import resolve_restaurant


class TenantRequestMixin:
    """Resolve ``request.restaurant`` *after* DRF authentication (JWT)."""

    def perform_authentication(self, request):
        super().perform_authentication(request)
        if request.user and request.user.is_authenticated and not getattr(request._request, "restaurant", None):
            request._request.restaurant = resolve_restaurant(request._request, request.user)
        request.restaurant = getattr(request._request, "restaurant", None)
        request.membership = getattr(request._request, "membership", None)


class TenantViewSet(TenantRequestMixin, viewsets.ModelViewSet):
    """ModelViewSet scoped to the current restaurant.

    Set ``perm`` to require a role permission for write actions
    (reads only need membership), or ``read_perm`` for reads too.
    """

    perm = None
    read_perm = None
    feature = None

    def get_permissions(self):
        from apps.accounts.permissions import require

        perms = [IsAuthenticated(), HasRestaurant()]
        needed = self.read_perm if self.request.method in ("GET", "HEAD", "OPTIONS") else self.perm
        if needed:
            perms.append(require(needed)())
        if self.feature:
            perms.append(FeatureEnabled(self.feature))
        return perms

    def get_queryset(self):
        return self.queryset.filter(restaurant=self.request.restaurant)

    def perform_create(self, serializer):
        serializer.save(restaurant=self.request.restaurant)


class FeatureEnabled:
    def __init__(self, code):
        self.code = code
        self.message = f"Your plan does not include this feature ({code}). Upgrade to unlock it."

    def has_permission(self, request, view):
        r = getattr(request, "restaurant", None)
        return bool(r and r.has_feature(self.code))

    def has_object_permission(self, request, view, obj):
        return True


class TenantSerializer(serializers.ModelSerializer):
    """Serializer that validates FK targets belong to the same restaurant."""

    def validate(self, attrs):
        request = self.context.get("request")
        r = getattr(request, "restaurant", None)
        if not r:
            return attrs

        def foreign(obj):
            return hasattr(obj, "restaurant_id") and obj.restaurant_id != r.id

        for k, v in attrs.items():
            values = v if isinstance(v, (list, tuple)) else [v]
            for obj in values:
                if foreign(obj) or (isinstance(obj, dict) and any(foreign(x) for x in obj.values())):
                    raise serializers.ValidationError({k: "Not found"})
        return attrs
