from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models

from apps.tenants.models import Restaurant

PERMISSIONS = {
    "pos": "Take orders & billing",
    "discount": "Apply discounts",
    "void": "Cancel orders / void items",
    "kitchen": "Kitchen display",
    "menu": "Manage menu",
    "tables": "Manage tables & rooms",
    "delivery": "Manage home delivery",
    "rider": "Deliver orders (rider app)",
    "inventory": "Manage inventory",
    "reports": "View reports",
    "customers": "Manage customers & loyalty",
    "staff": "Manage staff & roles",
    "settings": "Restaurant settings & hardware",
    "billing": "Subscription & payments",
}

DEFAULT_ROLES = {
    "Owner": list(PERMISSIONS),
    "Manager": [p for p in PERMISSIONS if p not in ("billing",)],
    "Cashier": ["pos", "discount", "customers"],
    "Captain": ["pos", "tables"],
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
