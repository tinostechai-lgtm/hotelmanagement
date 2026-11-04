import math
import random
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.tenants.models import TenantModel


def haversine_km(lat1, lng1, lat2, lng2):
    if None in (lat1, lng1, lat2, lng2):
        return None
    lat1, lng1, lat2, lng2 = map(lambda v: math.radians(float(v)), (lat1, lng1, lat2, lng2))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return round(6371 * 2 * math.asin(math.sqrt(a)), 2)


class DeliveryZone(TenantModel):
    """Distance slab or pincode-based delivery pricing."""

    name = models.CharField(max_length=60)
    max_km = models.DecimalField(max_digits=5, decimal_places=2, default=3)
    pincodes = models.CharField(max_length=300, blank=True, help_text="Comma separated, optional")
    fee = models.DecimalField(max_digits=8, decimal_places=2, default=30)
    min_order = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    eta_minutes = models.PositiveIntegerField(default=35)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["max_km"]

    def __str__(self):
        return f"{self.name} (≤{self.max_km} km)"


class Rider(TenantModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="rider_profiles")
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20)
    vehicle = models.CharField(max_length=40, blank=True)
    vehicle_number = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    is_online = models.BooleanField(default=False)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    per_delivery_pay = models.DecimalField(max_digits=8, decimal_places=2, default=30)

    def __str__(self):
        return self.name

    @property
    def active_tasks(self):
        return self.tasks.filter(status__in=DeliveryTask.ACTIVE)

    @property
    def cash_in_hand(self):
        unsettled = self.tasks.filter(status="delivered", settlement__isnull=True)
        return sum((t.cod_collected for t in unsettled), Decimal("0"))


class DeliveryTask(TenantModel):
    class Status(models.TextChoices):
        UNASSIGNED = "unassigned", "Unassigned"
        ASSIGNED = "assigned", "Assigned"
        ACCEPTED = "accepted", "Rider accepted"
        PICKED_UP = "picked_up", "Picked up"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed / returned"

    ACTIVE = ["unassigned", "assigned", "accepted", "picked_up"]

    order = models.OneToOneField("operations.Order", on_delete=models.CASCADE, related_name="delivery")
    rider = models.ForeignKey(Rider, null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.UNASSIGNED)
    distance_km = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    eta_minutes = models.PositiveIntegerField(default=35)
    otp = models.CharField(max_length=4, blank=True)
    cod_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cod_collected = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    assigned_at = models.DateTimeField(null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=160, blank=True)
    proof_note = models.CharField(max_length=160, blank=True)
    settlement = models.ForeignKey("Settlement", null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks")

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.otp:
            self.otp = f"{random.randint(0, 9999):04d}"
        super().save(*args, **kwargs)

    def assign(self, rider):
        self.rider = rider
        self.status = self.Status.ASSIGNED
        self.assigned_at = timezone.now()
        self.save()

    def mark_picked_up(self):
        self.status = self.Status.PICKED_UP
        self.picked_up_at = timezone.now()
        self.save()
        o = self.order
        if o.status in ("accepted", "preparing", "ready"):
            if o.status != "ready":
                o.status = "ready"
                o.save(update_fields=["status"])
            o.set_status("out_for_delivery")

    def mark_delivered(self, otp=None, cod_collected=None):
        if otp is not None and str(otp) != self.otp:
            raise ValueError("Incorrect delivery OTP")
        self.status = self.Status.DELIVERED
        self.delivered_at = timezone.now()
        self.cod_collected = self.cod_amount if cod_collected is None else Decimal(str(cod_collected))
        self.save()
        o = self.order
        if o.status == "out_for_delivery":
            o.set_status("delivered")


class RiderPing(models.Model):
    rider = models.ForeignKey(Rider, on_delete=models.CASCADE, related_name="pings")
    task = models.ForeignKey(DeliveryTask, null=True, blank=True, on_delete=models.CASCADE, related_name="pings")
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at"]


class Settlement(TenantModel):
    rider = models.ForeignKey(Rider, on_delete=models.CASCADE, related_name="settlements")
    cash_collected = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    rider_payout = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    deliveries = models.PositiveIntegerField(default=0)
    settled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]
