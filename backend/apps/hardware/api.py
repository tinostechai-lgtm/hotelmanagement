from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import action, api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.tenants.api_base import TenantSerializer, TenantViewSet

from . import services
from .models import Device, PrintJob


class DeviceSerializer(TenantSerializer):
    is_online = serializers.BooleanField(read_only=True)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    connection_display = serializers.CharField(source="get_connection_display", read_only=True)

    class Meta:
        model = Device
        exclude = ["restaurant"]
        read_only_fields = ["agent_key", "last_seen"]


class PrintJobSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source="device.name", read_only=True, default=None)
    connection = serializers.CharField(source="device.connection", read_only=True, default=None)
    address = serializers.CharField(source="device.address", read_only=True, default=None)

    class Meta:
        model = PrintJob
        exclude = ["restaurant"]


class DeviceViewSet(TenantViewSet):
    queryset = Device.objects.prefetch_related("stations")
    serializer_class = DeviceSerializer
    perm = "settings"

    def create(self, request, *args, **kwargs):
        sub = request.restaurant.subscription
        limit = sub.plan.max_devices if sub else 2
        if limit and self.get_queryset().count() >= limit:
            return Response({"detail": f"Your plan allows {limit} devices. Upgrade for unlimited hardware."}, status=403)
        return super().create(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def test(self, request, pk=None):
        jobs = services.print_test(self.get_object())
        return Response({"queued": len(jobs), "preview": jobs[0].text})

    @action(detail=False, methods=["post"], url_path="open-drawer")
    def open_drawer(self, request):
        services.open_drawer(request.restaurant)
        return Response({"ok": True})

    @action(detail=True, methods=["post"], url_path="rotate-key")
    def rotate_key(self, request, pk=None):
        d = self.get_object()
        d.agent_key = ""
        d.save()
        return Response({"agent_key": d.agent_key})


class PrintJobViewSet(TenantViewSet):
    """Browser / app printing: clients that print directly (WebUSB, Bluetooth,
    LAN socket from the Flutter app) poll ``?status=queued&connection=browser``
    and acknowledge with ``POST /api/print-jobs/{id}/ack``."""

    queryset = PrintJob.objects.select_related("device")
    serializer_class = PrintJobSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("device"):
            qs = qs.filter(device_id=p["device"])
        if p.get("unrouted"):
            from django.db.models import Q

            qs = qs.filter(Q(device__isnull=True) | Q(device__connection="browser"))
        return qs.order_by("-created_at")[:100] if not p.get("status") else qs

    def create(self, request, *args, **kwargs):
        return Response(status=405)

    @action(detail=True, methods=["post"])
    def ack(self, request, pk=None):
        job = self.get_object()
        job.status = "done" if request.data.get("ok", True) else "failed"
        job.error = request.data.get("error", "")[:200]
        job.attempts += 1
        job.save()
        return Response({"ok": True})

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        job = self.get_object()
        job.status = "queued"
        job.save()
        return Response({"ok": True})


def _device_from_key(request):
    key = request.headers.get("X-Device-Key") or request.query_params.get("key")
    return Device.objects.filter(agent_key=key, is_active=True).select_related("restaurant").first() if key else None


@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def agent_poll(request):
    """Servora Hardware Agent. One key per restaurant hub: the agent pulls jobs for
    *every* device in the restaurant that it can reach (network / USB / serial / BT).

    GET  -> {devices:[...], jobs:[...]}  (jobs are marked 'sent')
    POST -> {results:[{id, ok, error}], scale_weight?, scanned?}
    """
    hub = _device_from_key(request)
    if not hub:
        return Response({"detail": "Invalid device key"}, status=401)
    r = hub.restaurant
    Device.objects.filter(pk=hub.pk).update(last_seen=timezone.now())
    if request.method == "POST":
        for res in request.data.get("results", []):
            PrintJob.objects.filter(restaurant=r, pk=res.get("id")).update(
                status="done" if res.get("ok") else "failed", error=(res.get("error") or "")[:200])
        if "scale_weight" in request.data:
            Device.objects.filter(restaurant=r, kind="weighing_scale").update(
                config={"last_weight": request.data["scale_weight"], "at": timezone.now().isoformat()}, last_seen=timezone.now())
        if request.data.get("online_devices"):
            Device.objects.filter(restaurant=r, pk__in=request.data["online_devices"]).update(last_seen=timezone.now())
        return Response({"ok": True})
    devices = Device.objects.filter(restaurant=r, is_active=True).exclude(connection__in=["browser", "cloud", "hid"])
    jobs = list(PrintJob.objects.filter(restaurant=r, status__in=["queued"], device__in=devices).select_related("device")[:50])
    PrintJob.objects.filter(pk__in=[j.pk for j in jobs]).update(status="sent")
    return Response({
        "restaurant": r.name,
        "devices": [{"id": d.id, "name": d.name, "kind": d.kind, "connection": d.connection, "address": d.address,
                     "paper_width": d.paper_width, "config": d.config} for d in devices],
        "jobs": [{"id": j.id, "device": j.device_id, "kind": j.kind, "escpos_b64": j.escpos_b64, "text": j.text} for j in jobs],
    })


@api_view(["GET"])
def scale_reading(request):
    from apps.tenants.middleware import resolve_restaurant

    r = resolve_restaurant(request, request.user)
    d = Device.objects.filter(restaurant=r, kind="weighing_scale").first()
    return Response({"weight": (d.config or {}).get("last_weight") if d else None, "at": (d.config or {}).get("at") if d else None})
