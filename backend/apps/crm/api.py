from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.tenants.api_base import TenantSerializer, TenantViewSet

from .models import Address, Coupon, Customer, Feedback


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        exclude = ["customer"]


class CustomerSerializer(TenantSerializer):
    addresses = AddressSerializer(many=True, read_only=True)
    tier = serializers.CharField(read_only=True)

    class Meta:
        model = Customer
        exclude = ["restaurant"]
        read_only_fields = ["loyalty_points", "total_spent", "visits", "last_visit"]


class CouponSerializer(TenantSerializer):
    class Meta:
        model = Coupon
        exclude = ["restaurant"]
        read_only_fields = ["used_count"]


class FeedbackSerializer(TenantSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True, default="")

    class Meta:
        model = Feedback
        exclude = ["restaurant"]


class CustomerViewSet(TenantViewSet):
    queryset = Customer.objects.prefetch_related("addresses")
    serializer_class = CustomerSerializer
    perm = read_perm = "customers"

    def get_permissions(self):
        if self.action == "lookup":  # cashiers/captains can look up one number while billing
            from apps.accounts.permissions import require
            from rest_framework.permissions import IsAuthenticated

            return [IsAuthenticated(), require("pos")()]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.query_params.get("q")
        if q:
            from django.db.models import Q

            qs = qs.filter(Q(phone__icontains=q) | Q(name__icontains=q))
        return qs

    @action(detail=False)
    def lookup(self, request):
        c = self.get_queryset().filter(phone=request.query_params.get("phone", "")).first()
        return Response(CustomerSerializer(c).data if c else None)

    @action(detail=True)
    def orders(self, request, pk=None):
        from apps.operations.serializers import OrderListSerializer

        return Response(OrderListSerializer(self.get_object().orders.all()[:50], many=True).data)


class CouponViewSet(TenantViewSet):
    queryset = Coupon.objects.all()
    serializer_class = CouponSerializer
    perm = read_perm = "customers"


class FeedbackViewSet(TenantViewSet):
    queryset = Feedback.objects.select_related("customer")
    serializer_class = FeedbackSerializer
    perm = read_perm = "customers"


# ---------------------------------------------------------------------------
# Marketing
# ---------------------------------------------------------------------------
from rest_framework.decorators import api_view, permission_classes  # noqa: E402
from rest_framework.permissions import IsAuthenticated  # noqa: E402

from .models import Campaign  # noqa: E402

STORE_MARKETING_FIELDS = ["tagline", "cuisine", "seo_title", "seo_description", "cover_image_url", "offer_banner", "google_review_url",
                          "instagram_url", "facebook_url", "whatsapp_number", "logo_url", "brand_color"]


class CampaignSerializer(TenantSerializer):
    channel_display = serializers.CharField(source="get_channel_display", read_only=True)
    segment_display = serializers.CharField(source="get_segment_display", read_only=True)

    class Meta:
        model = Campaign
        exclude = ["restaurant"]
        read_only_fields = ["status", "sent", "failed", "created_by", "sent_at"]

    def validate_message(self, v):
        if len(v) > 1000:
            raise serializers.ValidationError("Keep messages under 1000 characters")
        return v


class CampaignViewSet(TenantViewSet):
    queryset = Campaign.objects.select_related("coupon")
    serializer_class = CampaignSerializer
    perm = read_perm = "marketing"
    feature = "crm"

    def perform_create(self, serializer):
        serializer.save(restaurant=self.request.restaurant, created_by=self.request.user)

    @action(detail=False, methods=["post"])
    def audience(self, request):
        """Preview: how many customers a segment reaches + a sample message."""
        from . import marketing

        c = Campaign(restaurant=request.restaurant, channel=request.data.get("channel", "whatsapp"), segment=request.data.get("segment", "all"),
                     tag=request.data.get("tag", ""), message=request.data.get("message", ""))
        if request.data.get("coupon"):
            c.coupon = Coupon.objects.filter(restaurant=request.restaurant, pk=request.data["coupon"]).first()
        qs = marketing.eligible(c)
        sample = qs.first()
        return Response({"count": qs.count(), "sample": marketing.render_message(c, sample) if sample else marketing.render_message(c, Customer(name="Priya"))})

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        from apps.accounts.models import AuditLog
        from apps.superadmin.models import get_settings

        from . import marketing

        campaign = self.get_object()
        ps = get_settings()
        ready = {"email": ps.email_enabled and ps.email_host, "sms": ps.sms_provider != "none",
                 "whatsapp": ps.whatsapp_enabled and ps.whatsapp_token}[campaign.channel]
        if not ready:
            return Response({"detail": f"{campaign.get_channel_display()} sending isn't set up on this platform yet. Please contact support."}, status=400)
        sent, failed, remaining = marketing.send_batch(campaign)
        if campaign.sent + campaign.failed == sent + failed:  # first batch
            AuditLog.record(request.restaurant, request.user, "campaign.send", campaign.name, f"{campaign.get_channel_display()} · {campaign.get_segment_display()}")
        return Response({"sent": sent, "failed": failed, "remaining": remaining, "campaign": CampaignSerializer(campaign).data})


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def store_profile(request):
    """Online-store SEO & social links — editable with the marketing permission."""
    from apps.tenants.middleware import resolve_restaurant

    r = resolve_restaurant(request, request.user)
    m = getattr(request, "membership", None)
    if not r or not m or not m.can("marketing"):
        return Response({"detail": "Marketing permission required"}, status=403)
    if request.method == "PATCH":
        from django.core.exceptions import ValidationError
        from django.core.validators import URLValidator

        changed = []
        for f in STORE_MARKETING_FIELDS:
            if f in request.data:
                v = str(request.data[f] or "").strip()
                if f.endswith("_url") and v:
                    try:
                        URLValidator(schemes=["https", "http"])(v)
                    except ValidationError:
                        return Response({f: "Enter a valid link starting with https://"}, status=400)
                if f == "brand_color" and v and not __import__("re").match(r"^#[0-9A-Fa-f]{6}$", v):
                    return Response({f: "Use a colour like #F4632F"}, status=400)
                max_len = r._meta.get_field(f).max_length
                if max_len and len(v) > max_len:
                    return Response({f: f"Max {max_len} characters"}, status=400)
                if getattr(r, f) != v:
                    setattr(r, f, v)
                    changed.append(f)
        if changed:
            r.save(update_fields=changed)
            from apps.accounts.models import AuditLog

            AuditLog.record(r, request.user, "settings.update", "Online store", "changed: " + ", ".join(changed))
    from .marketing import store_link

    return Response({**{f: getattr(r, f) for f in STORE_MARKETING_FIELDS}, "name": r.name, "slug": r.slug, "store_url": store_link(r)})
