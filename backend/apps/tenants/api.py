from datetime import date

from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .middleware import resolve_restaurant
from .models import Restaurant


class RestaurantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Restaurant
        exclude = ["owner"]
        read_only_fields = ["slug", "created_at"]


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def restaurant(request):
    r = resolve_restaurant(request, request.user)
    if not r:
        return Response({"detail": "No restaurant"}, status=404)
    if request.method == "PATCH":
        if not request.membership.can("settings"):
            return Response({"detail": "Settings permission required"}, status=403)
        s = RestaurantSerializer(r, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
    return Response(RestaurantSerializer(r).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reports(request):
    from apps.operations import reports as rep

    r = resolve_restaurant(request, request.user)
    m = getattr(request, "membership", None)
    if not r or not m or not m.can("reports"):
        return Response({"detail": "Reports permission required"}, status=403)
    p = request.query_params
    start = date.fromisoformat(p["start"]) if p.get("start") else None
    end = date.fromisoformat(p["end"]) if p.get("end") else None
    return Response(rep.summary(r, start, end))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def insights(request):
    from apps.operations import reports as rep

    r = resolve_restaurant(request, request.user)
    m = getattr(request, "membership", None)
    if not r or not m or not m.can("reports"):
        return Response({"detail": "Reports permission required"}, status=403)
    if not r.has_feature("analytics_ai"):
        return Response({"detail": "Smart insights are part of the Pro plan", "upgrade": True}, status=403)
    return Response(rep.insights(r))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pos_bootstrap(request):
    """Everything the POS / Flutter app needs in one call (cache for offline use)."""
    from apps.menu.api import menu_payload
    from apps.menu.models import KitchenStation
    from apps.operations.models import Area, Room, Table
    from apps.operations.serializers import RoomSerializer, TableSerializer

    r = resolve_restaurant(request, request.user)
    if not r:
        return Response({"detail": "No restaurant"}, status=404)
    return Response({
        "restaurant": RestaurantSerializer(r).data,
        "menu": menu_payload(r),
        "areas": [{"id": a.id, "name": a.name} for a in Area.objects.filter(restaurant=r)],
        "tables": TableSerializer(Table.objects.filter(restaurant=r).select_related("area"), many=True).data,
        "rooms": RoomSerializer(Room.objects.filter(restaurant=r), many=True).data if r.has_feature("room_service") else [],
        "stations": [{"id": s.id, "name": s.name} for s in KitchenStation.objects.filter(restaurant=r)],
        "payment_methods": [{"code": c, "name": n} for c, n in __import__("apps.operations.models", fromlist=["Payment"]).Payment.Method.choices
                            if c not in ("razorpay", "cod")],
        "features": r.subscription.plan.features if r.subscription and r.subscription.is_active else [],
        "permissions": request.membership.role.permissions if request.membership else [],
    })
