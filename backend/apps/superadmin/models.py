"""Platform-wide settings managed by the super admin (stored in the DB).

Secrets (API keys, passwords) are encrypted at rest with a key derived from
DJANGO_SECRET_KEY. If you rotate DJANGO_SECRET_KEY, re-enter the secrets.
"""
import base64
import hashlib
import time

from django.conf import settings
from django.db import models


def _fernet():
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(hashlib.sha256(("servora-settings:" + settings.SECRET_KEY).encode()).digest())
    return Fernet(key)


class EncryptedTextField(models.TextField):
    """Transparently encrypts on save and decrypts on load."""

    PREFIX = "enc:"

    def from_db_value(self, value, expression, connection):
        if not value or not value.startswith(self.PREFIX):
            return value or ""
        try:
            return _fernet().decrypt(value[len(self.PREFIX):].encode()).decode()
        except Exception:  # secret key changed: treat as unset
            return ""

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if not value:
            return ""
        return self.PREFIX + _fernet().encrypt(value.encode()).decode()


class PlatformSettings(models.Model):
    # General / branding
    site_name = models.CharField(max_length=80, default="Servora")
    site_url = models.URLField(blank=True, help_text="Public address used in emails & SMS links, e.g. https://servora.in")
    company_name = models.CharField(max_length=150, blank=True, help_text="Legal name printed on subscription invoices")
    company_address = models.TextField(blank=True)
    company_gstin = models.CharField("Company GSTIN", max_length=15, blank=True)
    support_email = models.EmailField(blank=True)
    support_phone = models.CharField(max_length=20, blank=True)
    announcement = models.CharField(max_length=255, blank=True, help_text="Banner shown to all restaurant users (leave empty to hide)")

    # Signup & trial
    signup_enabled = models.BooleanField(default=True, help_text="Allow new restaurants to sign up")
    trial_days = models.PositiveIntegerField(default=14)
    trial_plan = models.ForeignKey("subscriptions.Plan", null=True, blank=True, on_delete=models.SET_NULL,
                                   help_text="Plan used during the free trial (default: Pro)")
    grace_days = models.PositiveIntegerField(default=7, help_text="Days billing keeps working after a plan expires")

    # Razorpay
    razorpay_key_id = models.CharField("Razorpay Key ID", max_length=60, blank=True)
    razorpay_key_secret = EncryptedTextField("Razorpay Key Secret", blank=True)
    razorpay_webhook_secret = EncryptedTextField("Razorpay Webhook Secret", blank=True)

    # Email (SMTP)
    email_enabled = models.BooleanField(default=False)
    email_host = models.CharField("SMTP host", max_length=120, blank=True, help_text="e.g. smtp.gmail.com, smtp.zoho.in, email-smtp.ap-south-1.amazonaws.com")
    email_port = models.PositiveIntegerField("SMTP port", default=587)
    email_username = models.CharField("SMTP username", max_length=150, blank=True)
    email_password = EncryptedTextField("SMTP password / app password", blank=True)
    email_use_tls = models.BooleanField("Use STARTTLS (port 587)", default=True)
    email_use_ssl = models.BooleanField("Use SSL (port 465)", default=False)
    email_from = models.EmailField("From address", blank=True)
    email_from_name = models.CharField("From name", max_length=80, default="Servora")

    # SMS / WhatsApp
    SMS_PROVIDERS = [("none", "Disabled"), ("msg91", "MSG91"), ("twilio", "Twilio"), ("fast2sms", "Fast2SMS")]
    sms_provider = models.CharField(max_length=10, choices=SMS_PROVIDERS, default="none")
    sms_api_key = EncryptedTextField("SMS API key / auth token", blank=True)
    sms_account_sid = models.CharField("Account SID (Twilio)", max_length=60, blank=True)
    sms_sender_id = models.CharField("Sender ID / from number", max_length=20, blank=True)
    sms_template_id = models.CharField("DLT template ID (MSG91)", max_length=60, blank=True)
    whatsapp_enabled = models.BooleanField(default=False)
    whatsapp_token = EncryptedTextField("WhatsApp Cloud API token", blank=True)
    whatsapp_phone_number_id = models.CharField(max_length=40, blank=True)

    # Integrations
    google_maps_api_key = EncryptedTextField(blank=True)
    aggregator_webhook_secret = EncryptedTextField("Aggregator webhook secret", blank=True,
                                                   help_text="Shared HMAC secret for Swiggy/Zomato/UrbanPiper middleware")

    # SEO & analytics (marketing website + online stores)
    seo_title = models.CharField("Home page title", max_length=70, blank=True,
                                 help_text="≈60 characters. e.g. Servora — Restaurant POS, QR Ordering & Home Delivery")
    seo_description = models.CharField("Meta description", max_length=170, blank=True, help_text="≈155 characters shown under your link on Google")
    seo_keywords = models.CharField(max_length=255, blank=True, help_text="Comma separated, e.g. restaurant POS, billing software India")
    og_image_url = models.URLField("Social share image URL", blank=True, help_text="1200×630 image shown on WhatsApp, Facebook, LinkedIn")
    twitter_handle = models.CharField(max_length=40, blank=True)
    allow_indexing = models.BooleanField("Allow search engines to index the site", default=True)
    google_site_verification = models.CharField(max_length=100, blank=True, help_text="Content of the google-site-verification meta tag")
    bing_site_verification = models.CharField(max_length=100, blank=True)
    google_analytics_id = models.CharField("Google Analytics ID", max_length=30, blank=True, help_text="G-XXXXXXXXXX")
    google_tag_manager_id = models.CharField(max_length=30, blank=True, help_text="GTM-XXXXXXX")
    meta_pixel_id = models.CharField("Meta (Facebook) Pixel ID", max_length=30, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = verbose_name_plural = "Platform settings"

    def __str__(self):
        return "Platform settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        _cache.update(obj=None, at=0)


_cache = {"obj": None, "at": 0}


def get_settings(fresh=False):
    """Cached (30 s per serverless instance) singleton accessor."""
    if not fresh and _cache["obj"] is not None and time.time() - _cache["at"] < 30:
        return _cache["obj"]
    try:
        obj, _ = PlatformSettings.objects.get_or_create(pk=1)
    except Exception:  # table missing (before migrate) — use defaults
        obj = PlatformSettings(pk=1)
    _cache.update(obj=obj, at=time.time())
    return obj


# ---------------------------------------------------------------------------
# Platform team & role-based access
# ---------------------------------------------------------------------------

PLATFORM_PERMISSIONS = {
    "overview": "View dashboard & revenue numbers",
    "restaurants_view": "View restaurants & their details",
    "restaurants_create": "Add new clients (restaurant + owner login)",
    "restaurants_manage": "Change plans, validity & extend trials",
    "restaurants_suspend": "Suspend / re-activate restaurants",
    "restaurants_email": "Email restaurant owners",
    "plans": "Edit plans & pricing",
    "payments": "View subscription payments",
    "users": "View users, enable / disable accounts",
    "users_manage": "Add users to restaurants & reset passwords",
    "settings": "Platform settings & API keys (Razorpay, email, SMS)",
    "team": "Manage platform team & roles",
    "activity": "View platform activity log",
}

DEFAULT_PLATFORM_ROLES = {
    "Administrator": list(PLATFORM_PERMISSIONS),
    "Support": ["overview", "restaurants_view", "restaurants_create", "restaurants_manage", "restaurants_email", "users", "users_manage"],
    "Finance": ["overview", "restaurants_view", "payments", "plans", "activity"],
    "Sales": ["overview", "restaurants_view", "restaurants_create", "restaurants_email"],
}


class PlatformRole(models.Model):
    name = models.CharField(max_length=60, unique=True)
    description = models.CharField(max_length=200, blank=True)
    permissions = models.JSONField(default=list)
    is_system = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @classmethod
    def ensure_defaults(cls):
        for name, perms in DEFAULT_PLATFORM_ROLES.items():
            cls.objects.get_or_create(name=name, defaults={"permissions": perms, "is_system": True})


class PlatformStaff(models.Model):
    """A user who can access /superadmin/ with a limited role.
    Django superusers always have full access and don't need this."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="platform_staff")
    role = models.ForeignKey(PlatformRole, on_delete=models.PROTECT, related_name="members")
    is_active = models.BooleanField(default=True)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} ({self.role})"


def platform_permissions(user):
    """Set of platform permissions for a user (empty set = no access)."""
    if not user or not user.is_authenticated or not user.is_active:
        return set()
    if user.is_superuser:
        return set(PLATFORM_PERMISSIONS)
    try:
        staff = user.platform_staff
    except PlatformStaff.DoesNotExist:
        return set()
    return set(staff.role.permissions) if staff.is_active else set()


class PlatformAuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=60)
    target = models.CharField(max_length=150, blank=True)
    detail = models.CharField(max_length=500, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def record(cls, request, action, target="", detail=""):
        ip = (request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("REMOTE_ADDR") or "").split(",")[0].strip() or None
        return cls.objects.create(user=request.user if request.user.is_authenticated else None, action=action,
                                  target=str(target)[:150], detail=str(detail)[:500], ip=ip)
