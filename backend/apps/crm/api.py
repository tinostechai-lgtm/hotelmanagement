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
