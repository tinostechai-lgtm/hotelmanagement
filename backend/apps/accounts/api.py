import secrets

from django.contrib.auth import authenticate
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

from apps.tenants.api_base import TenantViewSet
from apps.tenants.middleware import resolve_restaurant

from .models import OWNER_ROLE, PERMISSION_GROUPS, PERMISSIONS, AuditLog, Membership, Role, User


class LoginThrottle(AnonRateThrottle):
    scope = "login"


class PinThrottle(UserRateThrottle):
    scope = "login"


def user_payload(user, request=None):
    ms = Membership.objects.filter(user=user, is_active=True).select_related("restaurant", "role")
    return {
        "id": user.id, "name": str(user), "phone": user.username, "email": user.email, "is_superuser": user.is_superuser,
        "memberships": [{"restaurant_id": m.restaurant_id, "restaurant": m.restaurant.name, "slug": m.restaurant.slug,
                         "business_type": m.restaurant.business_type, "role": m.role.name, "permissions": m.role.permissions,
                         "features": (m.restaurant.subscription.plan.features if m.restaurant.subscription and m.restaurant.subscription.is_active else []),
                         "plan": m.restaurant.subscription.plan.name if m.restaurant.subscription else None,
                         "brand_color": m.restaurant.brand_color}
                        for m in ms],
    }


def tokens(user):
    t = RefreshToken.for_user(user)
    return {"access": str(t.access_token), "refresh": str(t)}


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def login(request):
    phone = str(request.data.get("phone") or request.data.get("username") or "").strip()
    user = authenticate(request, username=phone, password=request.data.get("password", ""))
    if not user:
        return Response({"detail": "Invalid mobile number or password"}, status=401)
    return Response({**tokens(user), "user": user_payload(user)})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([PinThrottle])
def pin_switch(request):
    """Fast staff switching on a shared POS terminal using a 4–6 digit PIN."""
    r = resolve_restaurant(request, request.user)
    m = Membership.objects.filter(restaurant=r, is_active=True, user__pin=request.data.get("pin", "")).exclude(user__pin="").select_related("user").first()
    if not m:
        return Response({"detail": "Wrong PIN"}, status=401)
    return Response({**tokens(m.user), "user": user_payload(m.user)})


class SignupSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    phone = serializers.RegexField(r"^\+?\d{10,13}$")
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(min_length=8)
    restaurant_name = serializers.CharField(max_length=150)
    business_type = serializers.CharField(default="restaurant")
    city = serializers.CharField(required=False, allow_blank=True, default="")
    plan = serializers.CharField(required=False, default="pro")

    def validate_phone(self, v):
        if User.objects.filter(username=v).exists():
            raise serializers.ValidationError("This mobile number is already registered. Please log in.")
        return v


@transaction.atomic
def create_account(data):
    from apps.menu.models import KitchenStation
    from apps.operations.models import Area, Table
    from apps.subscriptions.models import Subscription
    from apps.tenants.models import Restaurant

    first, _, last = data["name"].partition(" ")
    user = User.objects.create_user(username=data["phone"], password=data["password"], email=data.get("email", ""),
                                    first_name=first, last_name=last, phone=data["phone"])
    r = Restaurant.objects.create(name=data["restaurant_name"], owner=user, phone=data["phone"], email=data.get("email", ""),
                                  business_type=data.get("business_type", "restaurant"), city=data.get("city", ""))
    Role.ensure_defaults(r)
    Membership.objects.create(user=user, restaurant=r, role=Role.objects.get(restaurant=r, name="Owner"))
    Subscription.start_trial(r)
    # Sensible starter setup so the POS works on minute one.
    KitchenStation.objects.create(restaurant=r, name="Kitchen")
    area = Area.objects.create(restaurant=r, name="Main")
    for i in range(1, 9):
        Table.objects.create(restaurant=r, area=area, name=str(i), seats=4)
    if user.email:
        from apps.superadmin.messaging import send_email

        sub = r.subscription
        transaction.on_commit(lambda: send_email(user.email, f"Welcome to Servora — {r.name} is ready", "welcome", {
            "name": user.first_name, "restaurant": r, "phone": user.username,
            "plan": sub.plan.name if sub else "", "trial_end": sub.current_period_end if sub else None}))
    return user, r


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def signup(request):
    from apps.superadmin.models import get_settings

    if not get_settings().signup_enabled:
        return Response({"detail": "New sign-ups are paused. Please contact support."}, status=403)
    s = SignupSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    user, _ = create_account(s.validated_data)
    return Response({**tokens(user), "user": user_payload(user)}, status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(user_payload(request.user))


class RoleSerializer(serializers.ModelSerializer):
    members = serializers.IntegerField(source="members.count", read_only=True)

    class Meta:
        model = Role
        exclude = ["restaurant"]
        read_only_fields = ["is_system"]

    def validate_permissions(self, v):
        bad = [p for p in v if p not in PERMISSIONS]
        if bad:
            raise serializers.ValidationError(f"Unknown permissions: {bad}")
        return v


def is_owner(request):
    m = getattr(request, "membership", None)
    return bool(m and m.role.name == OWNER_ROLE and m.role.is_system)


def can_grant(request, permissions):
    """Owners can grant anything; others only permissions they hold themselves."""
    if is_owner(request):
        return True
    return set(permissions or []) <= set(request.membership.role.permissions or [])


class RoleViewSet(TenantViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    perm = read_perm = "staff"

    def get_queryset(self):
        return Role.objects.filter(restaurant=self.request.restaurant)

    @action(detail=False)
    def catalog(self, request):
        return Response({"permissions": PERMISSIONS, "groups": PERMISSION_GROUPS, "owner_role": OWNER_ROLE,
                         "is_owner": is_owner(request), "my_permissions": request.membership.role.permissions})

    def perform_create(self, serializer):
        if not can_grant(self.request, serializer.validated_data.get("permissions")):
            raise serializers.ValidationError({"permissions": "You can't grant permissions you don't have"})
        role = serializer.save(restaurant=self.request.restaurant)
        AuditLog.record(self.request.restaurant, self.request.user, "role.create", role.name, ", ".join(role.permissions))

    def perform_update(self, serializer):
        role = serializer.instance
        if role.is_system and role.name == OWNER_ROLE:
            raise serializers.ValidationError({"detail": "The Owner role always has full access and can't be changed"})
        if "name" in serializer.validated_data and role.is_system and serializer.validated_data["name"] != role.name:
            raise serializers.ValidationError({"name": "Default roles can't be renamed"})
        new = serializer.validated_data.get("permissions", role.permissions)
        changed = set(new) ^ set(role.permissions)
        if not can_grant(self.request, changed):
            raise serializers.ValidationError({"permissions": "You can only add or remove permissions you have yourself"})
        if role == self.request.membership.role and not is_owner(self.request) and "staff" not in new:
            raise serializers.ValidationError({"permissions": "You can't remove staff access from your own role"})
        before = set(role.permissions)
        role = serializer.save()
        AuditLog.record(self.request.restaurant, self.request.user, "role.update", role.name,
                        "added: " + (", ".join(sorted(set(role.permissions) - before)) or "—") + " · removed: " +
                        (", ".join(sorted(before - set(role.permissions))) or "—"))

    def destroy(self, request, *args, **kwargs):
        role = self.get_object()
        if role.is_system or role.members.exists():
            return Response({"detail": "System roles or roles with members cannot be deleted"}, status=400)
        AuditLog.record(request.restaurant, request.user, "role.delete", role.name)
        return super().destroy(request, *args, **kwargs)


class StaffSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField()
    phone = serializers.CharField()
    email = serializers.EmailField(required=False, allow_blank=True)
    role = serializers.IntegerField()
    pin = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(required=False, write_only=True, allow_blank=True)
    is_active = serializers.BooleanField(default=True)


def staff_row(m):
    return {"id": m.id, "user_id": m.user_id, "name": str(m.user), "phone": m.user.username, "email": m.user.email,
            "role": m.role_id, "role_name": m.role.name, "is_active": m.is_active, "has_pin": bool(m.user.pin)}


class StaffViewSet(TenantViewSet):
    """Memberships of the current restaurant."""

    queryset = Membership.objects.select_related("user", "role")
    perm = read_perm = "staff"
    serializer_class = StaffSerializer

    def get_queryset(self):
        return Membership.objects.filter(restaurant=self.request.restaurant).select_related("user", "role")

    def list(self, request):
        return Response([staff_row(m) for m in self.get_queryset()])

    def retrieve(self, request, pk=None):
        return Response(staff_row(self.get_object()))

    @transaction.atomic
    def create(self, request):
        s = StaffSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        r = request.restaurant
        sub = r.subscription
        if sub and sub.plan.max_users and self.get_queryset().filter(is_active=True).count() >= sub.plan.max_users:
            return Response({"detail": f"Your plan allows {sub.plan.max_users} users. Upgrade to add more."}, status=403)
        role = get_object_or_404(Role, restaurant=r, pk=d["role"])
        if not can_grant(request, role.permissions):
            return Response({"detail": "You can't assign a role with more access than your own"}, status=403)
        user = User.objects.filter(username=d["phone"]).first()
        if not user:
            first, _, last = d["name"].partition(" ")
            user = User(username=d["phone"], phone=d["phone"], first_name=first, last_name=last, email=d.get("email", ""))
            user.set_password(d.get("password") or secrets.token_urlsafe(10))
        user.pin = d.get("pin", user.pin)
        user.save()
        m, created = Membership.objects.get_or_create(user=user, restaurant=r, defaults={"role": role})
        if not created:
            return Response({"detail": "This person is already in your team"}, status=400)
        AuditLog.record(r, request.user, "staff.add", user.username, role.name)
        return Response(staff_row(m), status=201)

    def partial_update(self, request, pk=None):
        m = self.get_object()
        d = request.data
        if m.role.name == OWNER_ROLE and m.role.is_system and not is_owner(request):
            return Response({"detail": "Only an owner can change another owner's account"}, status=403)
        if m.user_id == request.user.id and "role" in d and str(d["role"]) != str(m.role_id):
            return Response({"detail": "You can't change your own role"}, status=403)
        changes = []
        if "role" in d:
            new_role = get_object_or_404(Role, restaurant=request.restaurant, pk=d["role"])
            if new_role != m.role:
                if not can_grant(request, new_role.permissions):
                    return Response({"detail": "You can't assign a role with more access than your own"}, status=403)
                changes.append(f"role {m.role.name} → {new_role.name}")
            m.role = new_role
        if "is_active" in d:
            if m.user_id == request.restaurant.owner_id and not d["is_active"]:
                return Response({"detail": "The owner cannot be deactivated"}, status=400)
            if bool(d["is_active"]) != m.is_active:
                changes.append("enabled" if d["is_active"] else "disabled")
            m.is_active = bool(d["is_active"])
        m.save()
        u = m.user
        if d.get("name"):
            u.first_name, _, u.last_name = d["name"].partition(" ")
        if "pin" in d:
            u.pin = d["pin"]
        if d.get("password"):
            u.set_password(d["password"])
            changes.append("password reset")
        if "pin" in d and d["pin"] != u.pin:
            changes.append("PIN changed")
        u.save()
        if changes:
            AuditLog.record(request.restaurant, request.user, "staff.update", u.username, "; ".join(changes))
        return Response(staff_row(m))

    update = partial_update

    def destroy(self, request, pk=None):
        m = self.get_object()
        if m.user_id == request.restaurant.owner_id:
            return Response({"detail": "The owner cannot be removed"}, status=400)
        if m.role.name == OWNER_ROLE and not is_owner(request):
            return Response({"detail": "Only an owner can remove another owner"}, status=403)
        AuditLog.record(request.restaurant, request.user, "staff.remove", m.user.username, m.role.name)
        m.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AuditLogSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = ["id", "action", "target", "detail", "created_at", "user_name"]

    def get_user_name(self, obj):
        return str(obj.user) if obj.user else "System"


class AuditLogViewSet(TenantViewSet):
    queryset = AuditLog.objects.select_related("user")
    serializer_class = AuditLogSerializer
    perm = read_perm = "staff"
    http_method_names = ["get", "head", "options"]
