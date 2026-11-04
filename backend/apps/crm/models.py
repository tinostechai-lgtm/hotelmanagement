from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.tenants.models import TenantModel


class Customer(TenantModel):
    phone = models.CharField(max_length=20)
    name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    birthday = models.DateField(null=True, blank=True)
    anniversary = models.DateField(null=True, blank=True)
    loyalty_points = models.IntegerField(default=0)
    total_spent = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    visits = models.PositiveIntegerField(default=0)
    last_visit = models.DateTimeField(null=True, blank=True)
    tags = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    marketing_opt_in = models.BooleanField(default=True)

    class Meta:
        unique_together = ("restaurant", "phone")
        ordering = ["-last_visit", "name"]

    def __str__(self):
        return f"{self.name or 'Guest'} ({self.phone})"

    @property
    def tier(self):
        if self.total_spent >= 50000:
            return "Platinum"
        if self.total_spent >= 15000:
            return "Gold"
        if self.total_spent >= 5000:
            return "Silver"
        return "Bronze"

    def record_visit(self, amount, points_per_100=Decimal("5")):
        self.visits += 1
        self.total_spent += amount
        self.last_visit = timezone.now()
        earned = int(amount / 100 * points_per_100)
        self.loyalty_points += earned
        self.save()
        if earned:
            LoyaltyTransaction.objects.create(restaurant=self.restaurant, customer=self, points=earned, reason="Order")
        return earned


class Address(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="addresses")
    label = models.CharField(max_length=30, default="Home")
    line1 = models.CharField(max_length=200)
    line2 = models.CharField(max_length=200, blank=True)
    landmark = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=80, blank=True)
    pincode = models.CharField(max_length=10, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    def __str__(self):
        return ", ".join(p for p in [self.line1, self.line2, self.landmark, self.city, self.pincode] if p)


class LoyaltyTransaction(TenantModel):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="loyalty_txns")
    points = models.IntegerField()
    reason = models.CharField(max_length=80)


class Coupon(TenantModel):
    code = models.CharField(max_length=30)
    description = models.CharField(max_length=150, blank=True)
    is_percent = models.BooleanField(default=True)
    value = models.DecimalField(max_digits=10, decimal_places=2)
    max_discount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    min_order = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)
    usage_limit = models.PositiveIntegerField(default=0, help_text="0 = unlimited")
    used_count = models.PositiveIntegerField(default=0)
    online_only = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("restaurant", "code")

    def __str__(self):
        return self.code

    def discount_for(self, subtotal):
        """Return (discount, error)."""
        now = timezone.now()
        if not self.is_active or (self.valid_from and now < self.valid_from) or (self.valid_to and now > self.valid_to):
            return Decimal("0"), "Coupon is not active"
        if self.usage_limit and self.used_count >= self.usage_limit:
            return Decimal("0"), "Coupon usage limit reached"
        if subtotal < self.min_order:
            return Decimal("0"), f"Minimum order ₹{self.min_order}"
        d = subtotal * self.value / 100 if self.is_percent else self.value
        if self.max_discount:
            d = min(d, self.max_discount)
        return min(d, subtotal).quantize(Decimal("0.01")), None


class Feedback(TenantModel):
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.SET_NULL)
    order = models.ForeignKey("operations.Order", null=True, blank=True, on_delete=models.SET_NULL)
    rating = models.PositiveSmallIntegerField()
    food_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    service_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    comment = models.TextField(blank=True)


class Campaign(TenantModel):
    CHANNELS = [("whatsapp", "WhatsApp"), ("sms", "SMS"), ("email", "Email")]
    SEGMENTS = [("all", "All customers who opted in"), ("new", "New — 1 visit"), ("regulars", "Regulars — 5+ visits"),
                ("lapsed30", "Haven't visited in 30 days"), ("lapsed60", "Haven't visited in 60 days"),
                ("birthday", "Birthday this month"), ("top", "Top spenders (Gold & Platinum)"), ("tag", "Customers with a tag")]

    name = models.CharField(max_length=120)
    channel = models.CharField(max_length=10, choices=CHANNELS, default="whatsapp")
    segment = models.CharField(max_length=10, choices=SEGMENTS, default="all")
    tag = models.CharField(max_length=40, blank=True)
    subject = models.CharField(max_length=150, blank=True, help_text="Email subject")
    message = models.TextField(help_text="Use {name}, {restaurant}, {link}, {coupon}")
    coupon = models.ForeignKey(Coupon, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=10, default="draft")  # draft / sending / sent
    sent = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey("accounts.User", null=True, on_delete=models.SET_NULL, related_name="+")
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class CampaignDelivery(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="deliveries")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="+")
    ok = models.BooleanField(default=False)
    error = models.CharField(max_length=200, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("campaign", "customer")
