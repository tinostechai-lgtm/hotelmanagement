from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Restaurant(models.Model):
    """A tenant. Every operational record is scoped to one restaurant."""

    class BusinessType(models.TextChoices):
        RESTAURANT = "restaurant", "Restaurant"
        HOTEL = "hotel", "Hotel F&B"
        CAFE = "cafe", "Cafe / QSR"
        CLOUD_KITCHEN = "cloud_kitchen", "Cloud Kitchen"
        BAR = "bar", "Bar & Lounge"
        BAKERY = "bakery", "Bakery"

    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True)
    business_type = models.CharField(max_length=20, choices=BusinessType.choices, default=BusinessType.RESTAURANT)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="owned_restaurants")
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=80, blank=True)
    pincode = models.CharField(max_length=10, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gstin = models.CharField("GSTIN", max_length=15, blank=True)
    fssai = models.CharField("FSSAI No.", max_length=20, blank=True)
    logo_url = models.URLField(blank=True)
    brand_color = models.CharField(max_length=7, default="#F97316")
    currency = models.CharField(max_length=3, default="INR")

    # Billing behaviour
    gst_enabled = models.BooleanField("Charge GST on bills", default=False,
                                      help_text="Off: bills carry no GST at all (no tax lines, HSN or GSTIN on bills and screens)")
    prices_include_tax = models.BooleanField(default=False)
    service_charge_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    round_off_bills = models.BooleanField(default=True)
    bill_footer = models.CharField(max_length=255, blank=True, default="Thank you! Visit again.")

    # Online ordering & home delivery
    online_ordering_enabled = models.BooleanField(default=True)
    delivery_enabled = models.BooleanField(default=True)
    pickup_enabled = models.BooleanField(default=True)
    delivery_radius_km = models.DecimalField(max_digits=5, decimal_places=2, default=5)
    delivery_min_order = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=30)
    free_delivery_above = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    packaging_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    avg_prep_minutes = models.PositiveIntegerField(default=20)
    accept_cod = models.BooleanField(default=True)
    is_open = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True, help_text="Suspended restaurants can't log in or take online orders")

    # Online store SEO & marketing
    tagline = models.CharField(max_length=120, blank=True)
    cuisine = models.CharField(max_length=120, blank=True, help_text="e.g. North Indian, Chinese, Kerala")
    seo_title = models.CharField(max_length=70, blank=True)
    seo_description = models.CharField(max_length=170, blank=True)
    cover_image_url = models.URLField(blank=True)
    offer_banner = models.CharField(max_length=140, blank=True, help_text="Shown at the top of your online store")
    google_review_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    facebook_url = models.URLField(blank=True)
    whatsapp_number = models.CharField(max_length=20, blank=True)
    suspended_reason = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    @property
    def includes_tax(self):
        """Menu prices already contain GST (only meaningful when GST is charged)."""
        return self.gst_enabled and self.prices_include_tax

    def tax_rate_for(self, item):
        """GST % applied to an item on this restaurant's bills (0 when GST is off)."""
        return item.effective_tax if self.gst_enabled else 0

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:150] or "restaurant"
            slug, i = base, 1
            while Restaurant.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def subscription(self):
        return getattr(self, "_subscription_cache", None) or self.subscriptions.order_by("-created_at").first()

    def has_feature(self, code):
        sub = self.subscription
        return bool(sub and sub.is_active and sub.plan.has_feature(code))


class TenantModel(models.Model):
    """Abstract base for tenant-scoped records."""

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
