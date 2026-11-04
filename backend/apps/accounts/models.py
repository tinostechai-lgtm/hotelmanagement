from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models

from apps.tenants.models import Restaurant

PERMISSIONS = {
    "pos": "Take orders & billing",
    "discount": "Apply discounts & coupons",
    "void": "Cancel orders / void items sent to kitchen",
    "shifts": "Open / close cash shifts & cash drawer",
    "kitchen": "Kitchen display",
    "menu": "Manage menu & prices",
    "tables": "Manage tables, rooms & reservations setup",
    "delivery": "Manage home delivery & riders",
    "rider": "Deliver orders (rider app)",
    "inventory": "Manage inventory & purchases",
    "reports": "View sales reports & insights",
    "customers": "View & manage customers, loyalty, coupons",
    "marketing": "Marketing campaigns & online store SEO",
    "export": "Export data (CSV downloads)",
    "staff": "Manage staff, roles & view activity log",
    "settings": "Restaurant settings & hardware",
    "billing": "Subscription & payments",
}

# Grouping for the permission matrix UI.
PERMISSION_GROUPS = [
    ("Front of house", ["pos", "discount", "void", "shifts", "customers"]),
    ("Kitchen & delivery", ["kitchen", "delivery", "rider"]),
    ("Back office", ["menu", "tables", "inventory", "reports", "marketing", "export"]),
    ("Administration", ["staff", "settings", "billing"]),
]

OWNER_ROLE = "Owner"

DEFAULT_ROLES = {
    "Owner": list(PERMISSIONS),
    "Manager": [p for p in PERMISSIONS if p not in ("billing",)],
    "Cashier": ["pos", "discount", "customers", "shifts"],
    "Captain": ["pos"],
    "Kitchen": ["kitchen"],
    "Delivery Rider": ["rider"],
    "Store Keeper": ["inventory"],
}


class PhoneUserManager(UserManager):
    pass


class User(AbstractUser):
    """Users log in with their mobile number (stored as ``username``)."""

    phone = models.CharField(max_length=20, blank=True)
    pin = models.CharField(max_length=6, blank=True, help_text="Quick 4–6 digit PIN for POS switching")

    objects = PhoneUserManager()

    def __str__(self):
        return self.get_full_name() or self.username


class Role(models.Model):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="roles")
    name = models.CharField(max_length=60)
    permissions = models.JSONField(default=list)
    is_system = models.BooleanField(default=False)

    class Meta:
        unique_together = ("restaurant", "name")
        ordering = ["name"]

    def __str__(self):
        return self.name

    @classmethod
    def ensure_defaults(cls, restaurant):
        for name, perms in DEFAULT_ROLES.items():
            cls.objects.get_or_create(restaurant=restaurant, name=name, defaults={"permissions": perms, "is_system": True})


class Membership(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="memberships")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="members")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "restaurant")

    def __str__(self):
        return f"{self.user} @ {self.restaurant} ({self.role})"

    def can(self, perm):
        return perm in (self.role.permissions or [])


class AuditLog(models.Model):
    """Who did what in a restaurant — visible to owners & managers."""

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="audit_logs")
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=60)
    target = models.CharField(max_length=150, blank=True)
    detail = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["restaurant", "created_at"])]

    @classmethod
    def record(cls, restaurant, user, action, target="", detail=""):
        if restaurant is None:
            return None
        u = user if getattr(user, "is_authenticated", False) else None
        return cls.objects.create(restaurant=restaurant, user=u, action=action, target=str(target)[:150], detail=str(detail)[:500])
