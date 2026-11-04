from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.tenants.models import Restaurant

FEATURES = {
    "pos": "Fast billing & POS",
    "kot": "Kitchen Order Tickets (KOT)",
    "tables": "Table & floor management",
    "menu": "Menu, variants, add-ons & HSN/GST",
    "offline": "Offline billing (app)",
    "reports": "Sales reports",
    "qr_menu": "QR digital menu",
    "qr_ordering": "QR table ordering & payment",
    "split_bill": "Split billing",
    "kds": "Kitchen display system",
    "online_ordering": "Online ordering website",
    "delivery": "Home delivery management",
    "crm": "Customers, loyalty & coupons",
    "inventory": "Inventory & recipes",
    "room_service": "Hotel room service & room posting",
    "aggregators": "Swiggy / Zomato aggregator sync",
    "rider_app": "Rider app with live tracking",
    "analytics_ai": "AI forecasting & smart insights",
    "multi_outlet": "Multi-outlet management",
    "api_access": "Open API & webhooks",
}


class Plan(models.Model):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=50)
    tagline = models.CharField(max_length=140, blank=True)
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2)
    price_yearly = models.DecimalField(max_digits=10, decimal_places=2)
    features = models.JSONField(default=list)
    max_users = models.PositiveIntegerField(default=3, help_text="0 = unlimited")
    max_devices = models.PositiveIntegerField(default=2, help_text="0 = unlimited")
    max_outlets = models.PositiveIntegerField(default=1)
    is_popular = models.BooleanField(default=False)
    is_public = models.BooleanField(default=True)
    sort = models.PositiveIntegerField(default=0)
    razorpay_plan_monthly = models.CharField(max_length=40, blank=True)
    razorpay_plan_yearly = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["sort"]

    def __str__(self):
        return self.name

    def has_feature(self, code):
        return code in self.features

    def feature_labels(self):
        return [FEATURES[f] for f in self.features if f in FEATURES]

    @property
    def yearly_saving(self):
        return self.price_monthly * 12 - self.price_yearly


class Subscription(models.Model):
    class Status(models.TextChoices):
        TRIAL = "trial", "Trial"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Payment due"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    cycle = models.CharField(max_length=10, choices=[("monthly", "Monthly"), ("yearly", "Yearly")], default="monthly")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.TRIAL)
    current_period_start = models.DateTimeField(default=timezone.now)
    current_period_end = models.DateTimeField()
    razorpay_subscription_id = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.restaurant} — {self.plan} ({self.status})"

    @property
    def is_active(self):
        return self.status in (self.Status.TRIAL, self.Status.ACTIVE) and self.current_period_end >= timezone.now()

    @property
    def days_left(self):
        return max(0, (self.current_period_end - timezone.now()).days)

    def amount(self):
        return self.plan.price_yearly if self.cycle == "yearly" else self.plan.price_monthly

    def activate(self, cycle=None):
        self.cycle = cycle or self.cycle
        now = timezone.now()
        start = max(now, self.current_period_end) if self.status == self.Status.ACTIVE else now
        self.current_period_start = start
        self.current_period_end = start + timedelta(days=365 if self.cycle == "yearly" else 30)
        self.status = self.Status.ACTIVE
        self.save()

    @classmethod
    def start_trial(cls, restaurant, plan_code="pro", days=14):
        plan = Plan.objects.filter(code=plan_code).first() or Plan.objects.order_by("-sort").first()
        return cls.objects.create(restaurant=restaurant, plan=plan, status=cls.Status.TRIAL,
                                  current_period_end=timezone.now() + timedelta(days=days))


class SaasPayment(models.Model):
    """A Razorpay payment for a subscription plan."""

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="saas_payments")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    cycle = models.CharField(max_length=10, default="monthly")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    gst = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    razorpay_order_id = models.CharField(max_length=40, unique=True)
    razorpay_payment_id = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=10, default="created")  # created / paid / failed
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
