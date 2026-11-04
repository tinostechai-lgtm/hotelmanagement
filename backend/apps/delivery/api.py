from decimal import Decimal

from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tenants.api_base import TenantRequestMixin, TenantSerializer, TenantViewSet

from . import services
from .models import DeliveryTask, DeliveryZone, Rider, Settlement


class ZoneSerializer(TenantSerializer):
    class Meta:
        model = DeliveryZone
        exclude = ["restaurant"]


class RiderSerializer(TenantSerializer):
    active_tasks = serializers.IntegerField(source="active_tasks.count", read_only=True)
    cash_in_hand = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Rider
        exclude = ["restaurant"]


class TaskSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.number", read_only=True)
    order_id = serializers.IntegerField(source="order.id", read_only=True)
    order_status = serializers.CharField(source="order.status", read_only=True)
    customer_name = serializers.CharField(source="order.customer_name", read_only=True)
    customer_phone = serializers.CharField(source="order.customer_phone", read_only=True)
    address = serializers.CharField(source="order.delivery_address", read_only=True)
    lat = serializers.DecimalField(source="order.delivery_lat", max_digits=9, decimal_places=6, read_only=True)
    lng = serializers.DecimalField(source="order.delivery_lng", max_digits=9, decimal_places=6, read_only=True)
    total = serializers.DecimalField(source="order.total", max_digits=12, decimal_places=2, read_only=True)
    is_paid = serializers.BooleanField(source="order.is_paid", read_only=True)
    rider_name = serializers.CharField(source="rider.name", read_only=True, default=None)
    items = serializers.SerializerMethodField()

    class Meta:
        model = DeliveryTask
        exclude = ["restaurant", "otp"]

    def get_items(self, t):
        return [f"{li.quantity.normalize():f} x {li.display_name}" for li in t.order.items.filter(is_void=False)]


class ZoneViewSet(TenantViewSet):
    queryset = DeliveryZone.objects.all()
    serializer_class = ZoneSerializer
    perm = "delivery"
    feature = "delivery"


class RiderViewSet(TenantViewSet):
    queryset = Rider.objects.all()
    serializer_class = RiderSerializer
    perm = "delivery"
    feature = "delivery"

    def perform_create(self, serializer):
        import re

        from apps.accounts.models import Membership

        rider = serializer.save(restaurant=self.request.restaurant)
        digits = re.sub(r"\D", "", rider.phone)[-10:]
        m = next((m for m in Membership.objects.filter(restaurant=rider.restaurant).select_related("user")
                  if re.sub(r"\D", "", m.user.username)[-10:] == digits), None) if digits else None
        if m and not Rider.objects.filter(user=m.user, restaurant=rider.restaurant).exclude(pk=rider.pk).exists():
            rider.user = m.user
            rider.save(update_fields=["user"])

    @action(detail=True, methods=["post"])
    def settle(self, request, pk=None):
        s = services.settle_rider(self.get_object(), request.user, request.data.get("notes", ""))
        return Response({"id": s.id, "cash_collected": str(s.cash_collected), "rider_payout": str(s.rider_payout), "deliveries": s.deliveries})


class TaskViewSet(TenantViewSet):
    queryset = DeliveryTask.objects.select_related("order", "rider")
    serializer_class = TaskSerializer
    perm = "delivery"
    feature = "delivery"
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get("active"):
            qs = qs.filter(status__in=DeliveryTask.ACTIVE).exclude(order__status="cancelled")
        return qs

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        task = self.get_object()
        if request.data.get("auto"):
            if not services.auto_assign(task):
                return Response({"detail": "No rider is online"}, status=400)
        else:
            task.assign(get_object_or_404(Rider, restaurant=request.restaurant, pk=request.data.get("rider")))
        return Response(TaskSerializer(task).data)

    @action(detail=True, methods=["post"])
    def pickup(self, request, pk=None):
        task = self.get_object()
        task.mark_picked_up()
        return Response(TaskSerializer(task).data)

    @action(detail=True, methods=["post"])
    def deliver(self, request, pk=None):
        task = self.get_object()
        try:
            task.mark_delivered(None, request.data.get("cod_collected"))
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        return Response(TaskSerializer(task).data)


class SettlementViewSet(TenantViewSet):
    queryset = Settlement.objects.select_related("rider")
    perm = "delivery"
    http_method_names = ["get", "head", "options"]

    class _S(serializers.ModelSerializer):
        rider_name = serializers.CharField(source="rider.name", read_only=True)

        class Meta:
            model = Settlement
            exclude = ["restaurant"]

    serializer_class = _S


class RiderAppView(TenantRequestMixin, APIView):
    """Endpoints used by the rider mode of the Flutter app."""

    permission_classes = [IsAuthenticated]

    def rider(self, request):
        from .models import link_rider_for

        m = getattr(request, "membership", None)
        if not request.restaurant or not m or not m.can("rider"):
            return Rider.objects.filter(user=request.user, restaurant=request.restaurant, is_active=True).first()
        rider = link_rider_for(request.user, request.restaurant)
        return rider if rider.is_active else None

    def get(self, request):
        rider = self.rider(request)
        if not rider:
            return Response({"detail": "You are not registered as a rider"}, status=403)
        tasks = rider.tasks.filter(status__in=["assigned", "accepted", "picked_up"]).select_related("order")
        done = rider.tasks.filter(status="delivered", settlement__isnull=True)
        return Response({"rider": RiderSerializer(rider).data, "tasks": TaskSerializer(tasks, many=True).data,
                         "unsettled_deliveries": done.count(), "cash_in_hand": str(rider.cash_in_hand),
                         "restaurant": {"name": request.restaurant.name, "lat": request.restaurant.latitude, "lng": request.restaurant.longitude,
                                        "phone": request.restaurant.phone}})

    def post(self, request):
        """{action: online|offline|ping|accept|pickup|deliver|fail, task?, lat?, lng?, otp?, cod_collected?, reason?}"""
        rider = self.rider(request)
        if not rider:
            return Response({"detail": "You are not registered as a rider"}, status=403)
        act = request.data.get("action")
        if act in ("online", "offline"):
            rider.is_online = act == "online"
            rider.save(update_fields=["is_online"])
            return Response({"is_online": rider.is_online})
        if act == "ping":
            services.ping(rider, Decimal(str(request.data["lat"])), Decimal(str(request.data["lng"])))
            return Response({"ok": True})
        task = get_object_or_404(DeliveryTask, rider=rider, pk=request.data.get("task"))
        try:
            if act == "accept":
                task.status = "accepted"
                task.save(update_fields=["status"])
            elif act == "pickup":
                task.mark_picked_up()
            elif act == "deliver":
                task.mark_delivered(request.data.get("otp"), request.data.get("cod_collected"))
            elif act == "fail":
                task.status = "failed"
                task.failure_reason = request.data.get("reason", "")
                task.save()
            else:
                return Response({"detail": "Unknown action"}, status=400)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        return Response(TaskSerializer(task).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def live_map(request):
    from apps.tenants.middleware import resolve_restaurant

    r = resolve_restaurant(request, request.user)
    riders = Rider.objects.filter(restaurant=r, is_active=True)
    tasks = DeliveryTask.objects.filter(restaurant=r, status__in=DeliveryTask.ACTIVE).select_related("order", "rider")
    return Response({
        "restaurant": {"lat": r.latitude, "lng": r.longitude, "name": r.name},
        "riders": [{"id": x.id, "name": x.name, "lat": x.latitude, "lng": x.longitude, "online": x.is_online,
                    "active": x.active_tasks.count(), "last_seen": x.last_seen} for x in riders],
        "tasks": TaskSerializer(tasks, many=True).data,
    })
