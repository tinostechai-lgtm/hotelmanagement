from django import forms
from django.contrib.auth import get_user_model

from apps.subscriptions.models import FEATURES, Plan

from .models import EncryptedTextField, PlatformSettings

SECTIONS = {
    "general": ("General & branding", ["site_name", "site_url", "company_name", "company_address", "company_gstin",
                                       "support_email", "support_phone", "announcement"]),
    "signup": ("Sign-up & trial", ["signup_enabled", "trial_days", "trial_plan", "grace_days"]),
    "payments": ("Razorpay payments", ["razorpay_key_id", "razorpay_key_secret", "razorpay_webhook_secret"]),
    "email": ("Email (SMTP)", ["email_enabled", "email_host", "email_port", "email_use_tls", "email_use_ssl",
                               "email_username", "email_password", "email_from", "email_from_name"]),
    "sms": ("SMS & WhatsApp", ["sms_provider", "sms_api_key", "sms_account_sid", "sms_sender_id", "sms_template_id",
                               "whatsapp_enabled", "whatsapp_token", "whatsapp_phone_number_id"]),
    "seo": ("SEO & analytics", ["seo_title", "seo_description", "seo_keywords", "og_image_url", "twitter_handle", "allow_indexing",
                                "google_site_verification", "bing_site_verification", "google_analytics_id", "google_tag_manager_id",
                                "meta_pixel_id"]),
    "integrations": ("Maps & integrations", ["google_maps_api_key", "aggregator_webhook_secret"]),
}


def settings_form(section):
    _, fields = SECTIONS[section]

    class _Form(forms.ModelForm):
        class Meta:
            model = PlatformSettings
            fields = SECTIONS[section][1]
            widgets = {"company_address": forms.Textarea(attrs={"rows": 3}), "seo_description": forms.Textarea(attrs={"rows": 3, "maxlength": 170})}

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.secret_fields = []
            for name in list(self.fields):
                mf = PlatformSettings._meta.get_field(name)
                if isinstance(mf, EncryptedTextField):
                    self.secret_fields.append(name)
                    current = getattr(self.instance, name)
                    self.fields[name] = forms.CharField(
                        label=mf.verbose_name[:1].upper() + mf.verbose_name[1:], required=False,
                        widget=forms.PasswordInput(attrs={"autocomplete": "new-password",
                                                          "placeholder": "•••••••• saved — leave blank to keep" if current else "Not set"}),
                        help_text=mf.help_text)
                    if current:
                        self.fields[name + "__clear"] = forms.BooleanField(required=False, label=f"Remove saved {mf.verbose_name.lower()}")
            order = []
            for name in fields:
                order += [name] + ([name + "__clear"] if name + "__clear" in self.fields else [])
            self.order_fields(order)

        def clean(self):
            import re

            data = super().clean()
            for f, pat in {"google_analytics_id": r"^(G|UA|AW)-[A-Z0-9-]+$", "google_tag_manager_id": r"^GTM-[A-Z0-9]+$",
                           "meta_pixel_id": r"^\d{6,20}$", "google_site_verification": r"^[\w-]+$", "bing_site_verification": r"^[\w-]+$",
                           "twitter_handle": r"^@?\w{1,30}$"}.items():
                if data.get(f) and not re.match(pat, data[f].strip()):
                    self.add_error(f, "This doesn't look like a valid ID")
            for name in self.secret_fields:
                if data.get(name + "__clear"):
                    data[name] = ""
                elif not data.get(name):
                    data[name] = getattr(self.instance, name)  # keep existing
            return data

    return _Form


class PlanForm(forms.ModelForm):
    features = forms.MultipleChoiceField(choices=list(FEATURES.items()), widget=forms.CheckboxSelectMultiple, required=False)

    class Meta:
        model = Plan
        fields = ["code", "name", "tagline", "price_monthly", "price_yearly", "max_users", "max_devices", "max_outlets",
                  "features", "is_popular", "is_public", "sort"]


class SubscriptionAdjustForm(forms.Form):
    plan = forms.ModelChoiceField(queryset=Plan.objects.all())
    status = forms.ChoiceField(choices=[("trial", "Trial"), ("active", "Active"), ("past_due", "Payment due"), ("cancelled", "Cancelled"), ("expired", "Expired")])
    cycle = forms.ChoiceField(choices=[("monthly", "Monthly"), ("yearly", "Yearly")])
    valid_till = forms.DateTimeField(widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"))


class SetupForm(forms.Form):
    name = forms.CharField(max_length=150)
    phone = forms.RegexField(r"^\+?\d{10,13}$", help_text="You'll log in with this mobile number")
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput, min_length=10, help_text="At least 10 characters")
    site_url = forms.URLField(required=False)

    def clean_phone(self):
        v = self.cleaned_data["phone"]
        if get_user_model().objects.filter(username=v).exists():
            raise forms.ValidationError("This mobile number is already registered")
        return v


BUSINESS_TYPES = [("restaurant", "Restaurant"), ("hotel", "Hotel F&B"), ("cafe", "Cafe / QSR"), ("cloud_kitchen", "Cloud kitchen"),
                  ("bar", "Bar & lounge"), ("bakery", "Bakery")]


def _phone_free(v):
    if get_user_model().objects.filter(username=v).exists():
        raise forms.ValidationError("This mobile number already has an account")
    return v


class AddClientForm(forms.Form):
    restaurant_name = forms.CharField(max_length=150)
    business_type = forms.ChoiceField(choices=BUSINESS_TYPES)
    city = forms.CharField(max_length=80, required=False)
    gstin = forms.CharField(label="GSTIN", max_length=15, required=False)
    owner_name = forms.CharField(max_length=150)
    owner_phone = forms.RegexField(r"^\+?\d{10,13}$", label="Owner mobile (login)")
    owner_email = forms.EmailField(required=False, help_text="Login details are emailed here (if email is configured)")
    password = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False), min_length=8,
                               help_text="Leave blank to generate one — it is shown once after saving")
    plan = forms.ModelChoiceField(queryset=Plan.objects.all())
    status = forms.ChoiceField(choices=[("trial", "Free trial"), ("active", "Active (paid / offline payment)")])
    days = forms.IntegerField(min_value=1, max_value=3650, initial=14, label="Valid for (days)")
    send_email = forms.BooleanField(required=False, initial=True, label="Email login details to the owner")

    def clean_owner_phone(self):
        return _phone_free(self.cleaned_data["owner_phone"])


class AddRestaurantUserForm(forms.Form):
    name = forms.CharField(max_length=150)
    phone = forms.RegexField(r"^\+?\d{10,13}$", label="Mobile (login)")
    email = forms.EmailField(required=False)
    role = forms.ModelChoiceField(queryset=None)
    password = forms.CharField(required=False, widget=forms.PasswordInput, min_length=8, help_text="Leave blank to generate one")

    def __init__(self, restaurant, *a, **kw):
        super().__init__(*a, **kw)
        from apps.accounts.models import Role

        self.restaurant = restaurant
        self.fields["role"].queryset = Role.objects.filter(restaurant=restaurant)

    def clean_phone(self):
        from apps.accounts.models import Membership

        v = self.cleaned_data["phone"]
        if Membership.objects.filter(restaurant=self.restaurant, user__username=v).exists():
            raise forms.ValidationError("Already a member of this restaurant")
        return v


class TeamMemberForm(forms.Form):
    name = forms.CharField(max_length=150)
    phone = forms.RegexField(r"^\+?\d{10,13}$", label="Mobile (login)", help_text="Existing users keep their password")
    email = forms.EmailField(required=False)
    role = forms.ModelChoiceField(queryset=None)
    password = forms.CharField(required=False, widget=forms.PasswordInput, min_length=10,
                               help_text="For new users. Leave blank to generate one")

    def __init__(self, *a, **kw):
        from .models import PlatformRole

        super().__init__(*a, **kw)
        self.fields["role"].queryset = PlatformRole.objects.all()


class PlatformRoleForm(forms.ModelForm):
    permissions = forms.MultipleChoiceField(choices=[], widget=forms.CheckboxSelectMultiple, required=False)

    class Meta:
        from .models import PlatformRole

        model = PlatformRole
        fields = ["name", "description", "permissions"]

    def __init__(self, *a, allowed=None, **kw):
        from .models import PLATFORM_PERMISSIONS

        super().__init__(*a, **kw)
        self.allowed = allowed if allowed is not None else set(PLATFORM_PERMISSIONS)
        self.fields["permissions"].choices = list(PLATFORM_PERMISSIONS.items())

    def clean_permissions(self):
        perms = self.cleaned_data["permissions"]
        extra = set(perms) - self.allowed
        if extra:
            raise forms.ValidationError("You can't grant permissions you don't have yourself")
        return perms
