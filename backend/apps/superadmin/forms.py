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
    "integrations": ("Maps & integrations", ["google_maps_api_key", "aggregator_webhook_secret"]),
}


def settings_form(section):
    _, fields = SECTIONS[section]

    class _Form(forms.ModelForm):
        class Meta:
            model = PlatformSettings
            fields = SECTIONS[section][1]
            widgets = {"company_address": forms.Textarea(attrs={"rows": 3})}

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
            data = super().clean()
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
