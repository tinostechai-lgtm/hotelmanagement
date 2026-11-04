"""Public (no-login) endpoints: QR table ordering, online store, order tracking,
customer Razorpay payments, and aggregator (Swiggy/Zomato/others) webhooks."""
import hashlib
import hmac
from decimal import Decimal

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from apps.menu.api import menu_payload
from apps.subscriptions import razorpay_client
from apps.tenants.models import Restaurant

from . import services
from .models import Order, Payment, Room, Table
from .serializers import LineSpec


class OrderThrottle(AnonRateThrottle):
    rate = "30/min"


def public(fn):
    fn = authentication_classes([])(fn)
    return permission_classes([AllowAny])(fn)


def _restaurant(slug):
    return get_object_or_404(Restaurant, slug=slug, is_active=True)


def store_info(r):
    return {"name": r.name, "slug": r.slug, "logo_url": r.logo_url, "brand_color": r.brand_color, "address": r.address,
            "phone": r.phone, "is_open": r.is_open, "online_ordering": r.online_ordering_enabled and r.has_feature("online_ordering"),
            "delivery": r.delivery_enabled and r.has_feature("delivery"), "pickup": r.pickup_enabled, "accept_cod": r.accept_cod,
            "delivery_fee": str(r.delivery_fee), "free_delivery_above": str(r.free_delivery_above), "min_order": str(r.delivery_min_order),
            "packaging_charge": str(r.packaging_charge), "prep_minutes": r.avg_prep_minutes, "lat": r.latitude, "lng": r.longitude,
            "qr_ordering": r.has_feature("qr_ordering"), "razorpay_key": razorpay_client.key_id(),
            "razorpay_demo": not razorpay_client.enabled(), "prices_include_tax": r.prices_include_tax}


@api_view(["GET"])
@public
def store(request, slug):
    r = _restaurant(slug)
    ctx = {}
    t = request.query_params.get("table")
    if t:
        table = Table.objects.filter(restaurant=r, qr_token=t).first()
        ctx = {"table": {"name": table.name, "token": table.qr_token}} if table else {"invalid_qr": "table"}
    rm = request.query_params.get("room")
    if rm:
        room = Room.objects.filter(restaurant=r, qr_token=rm).first()
        ctx = {"room": {"number": room.number, "token": room.qr_token}} if room else {"invalid_qr": "room"}
    return Response({"store": store_info(r), "menu": menu_payload(r, online=not ctx), **ctx})


@api_view(["POST"])
@public
def delivery_quote(request, slug):
    from apps.delivery.services import quote

    r = _restaurant(slug)
    d = request.data
    q = quote(r, d.get("lat"), d.get("lng"), d.get("pincode", ""), Decimal(str(d.get("subtotal", 0))))
    return Response({k: (str(v) if isinstance(v, Decimal) else v) for k, v in q.items()})


class PublicOrderSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=["dine_in", "takeaway", "delivery", "room_service"])
    table_token = serializers.CharField(required=False, allow_blank=True)
    room_token = serializers.CharField(required=False, allow_blank=True)
    name = serializers.CharField(max_length=120)
    phone = serializers.RegexField(r"^\+?\d{10,13}$")
    email = serializers.EmailField(required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True, default="")
    lat = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    coupon = serializers.CharField(required=False, allow_blank=True, default="")
    payment = serializers.ChoiceField(choices=["online", "cod", "later"], default="online")
    items = LineSpec(many=True)


@api_view(["POST"])
@public
@throttle_classes([OrderThrottle])
def place_order(request, slug):
    r = _restaurant(slug)
    s = PublicOrderSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    d = s.validated_data
    table = room = None
    if d["mode"] == "dine_in":
        if not r.has_feature("qr_ordering"):
            return Response({"detail": "QR ordering is not enabled for this restaurant"}, status=403)
        table = get_object_or_404(Table, restaurant=r, qr_token=d.get("table_token"))
    elif d["mode"] == "room_service":
        room = get_object_or_404(Room, restaurant=r, qr_token=d.get("room_token"))
    else:
        if not (r.online_ordering_enabled and r.has_feature("online_ordering")):
            return Response({"detail": "Online ordering is not available"}, status=403)
        if not r.is_open:
            return Response({"detail": "The restaurant is closed right now"}, status=400)
        if d["mode"] == "delivery":
            if not (r.delivery_enabled and r.has_feature("delivery")):
                return Response({"detail": "Home delivery is not available"}, status=400)
            if not d.get("address"):
                return Response({"detail": "Delivery address is required"}, status=400)
            from apps.delivery.services import quote

            q = quote(r, d.get("lat"), d.get("lng"))
            if not q["serviceable"]:
                return Response({"detail": q["message"]}, status=400)
        if d["payment"] == "cod" and not r.accept_cod:
            return Response({"detail": "Cash on delivery is not accepted"}, status=400)
    try:
        order = services.create_order(
            r, order_type=d["mode"], source="qr" if table or room else "online", table=table, room=room,
            customer_phone=d["phone"], customer_name=d["name"], customer_email=d.get("email", ""), notes=d["notes"],
            items=[dict(i) for i in d["items"]], delivery_address=d.get("address", ""), delivery_lat=d.get("lat"),
            delivery_lng=d.get("lng"), coupon_code=d.get("coupon", ""), payment_mode=d["payment"])
        if d["mode"] == "delivery" and order.subtotal < r.delivery_min_order:
            services.cancel_order(order, "Below minimum order")
            return Response({"detail": f"Minimum order for delivery is ₹{r.delivery_min_order}"}, status=400)
    except services.OrderError as e:
        return Response({"detail": str(e)}, status=400)
    resp = {"order": _track(order)}
    if d["payment"] != "online":
        from apps.superadmin.messaging import notify_customer

        notify_customer(order, "placed")
    if d["payment"] == "online":
        rz = razorpay_client.create_order(order.total, f"ord-{order.id}", {"restaurant": r.slug, "order": order.number})
        Payment.objects.create(restaurant=r, order=order, method="razorpay", amount=order.total, status="pending", razorpay_order_id=rz["id"])
        resp["razorpay"] = {"key": razorpay_client.key_id(), "order_id": rz["id"], "amount": rz["amount"],
                            "currency": "INR", "name": r.name, "demo": bool(rz.get("demo")),
                            "prefill": {"name": d["name"], "contact": d["phone"], "email": d.get("email", "")}}
    return Response(resp, status=201)


@api_view(["POST"])
@public
def verify_payment(request, slug):
    r = _restaurant(slug)
    d = request.data
    p = Payment.objects.filter(restaurant=r, razorpay_order_id=d.get("razorpay_order_id")).select_related("order").first()
    if not p:
        return Response({"detail": "Payment not found"}, status=404)
    if not razorpay_client.verify_payment(d.get("razorpay_order_id"), d.get("razorpay_payment_id"), d.get("razorpay_signature")):
        p.status = "failed"
        p.save()
        return Response({"detail": "Payment verification failed"}, status=400)
    if p.status != "success":
        services.confirm_payment(p, d.get("razorpay_payment_id", ""))
        from apps.superadmin.messaging import notify_customer

        notify_customer(p.order, "placed")
    if hasattr(p.order, "delivery"):
        p.order.delivery.cod_amount = 0
        p.order.delivery.save(update_fields=["cod_amount"])
    return Response({"order": _track(p.order)})


def _track(o):
    d = getattr(o, "delivery", None)
    steps = ["pending", "accepted", "preparing", "ready"] + (["out_for_delivery", "delivered"] if o.order_type == "delivery" else ["served"])
    return {
        "number": o.number, "token": o.tracking_token, "status": o.status, "review_url": o.restaurant.google_review_url, "status_display": o.get_status_display(),
        "steps": steps, "type": o.order_type, "restaurant": o.restaurant.name, "created_at": o.created_at,
        "items": [{"name": li.display_name, "qty": f"{li.quantity.normalize():f}", "amount": str(li.line_total)} for li in o.live_items()],
        "subtotal": str(o.subtotal), "discount": str(o.discount), "tax": str(o.tax), "delivery_fee": str(o.delivery_fee),
        "packaging": str(o.packaging_charge), "service_charge": str(o.service_charge), "total": str(o.total), "is_paid": o.is_paid,
        "delivery": {"status": d.status, "rider": d.rider.name if d.rider else None, "rider_phone": d.rider.phone if d.rider else None,
                     "rider_lat": d.rider.latitude if d.rider else None, "rider_lng": d.rider.longitude if d.rider else None,
                     "eta_minutes": d.eta_minutes, "otp": d.otp} if d else None,
    }


@api_view(["GET"])
@public
def track(request, token):
    return Response(_track(get_object_or_404(Order, tracking_token=token)))


@api_view(["POST"])
@public
def call_waiter(request, slug):
    from .models import Notification

    r = _restaurant(slug)
    t = get_object_or_404(Table, restaurant=r, qr_token=request.data.get("table_token"))
    what = request.data.get("request", "waiter")[:40]
    Notification.objects.create(restaurant=r, kind="table_call", title=f"Table {t.name} requested {what}", link="/app/tables/")
    return Response({"ok": True})


@api_view(["POST"])
@public
def feedback(request, token):
    from apps.crm.models import Feedback

    o = get_object_or_404(Order, tracking_token=token)
    Feedback.objects.create(restaurant=o.restaurant, order=o, customer=o.customer, rating=int(request.data.get("rating", 5)),
                            comment=str(request.data.get("comment", ""))[:1000])
    return Response({"ok": True})


@api_view(["POST"])
@public
def aggregator_webhook(request, slug, source):
    """Normalised aggregator intake. Point your Swiggy / Zomato / Magicpin /
    UrbanPiper integration at ``/api/integrations/<slug>/<source>/order``.

    Expected JSON (any middleware can map to this)::

        {"external_id": "SWG123", "customer": {"name": "", "phone": "", "address": ""},
         "items": [{"item_id": 1 | "name": "Paneer Tikka", "quantity": 2, "price": 260}],
         "type": "delivery|takeaway", "notes": "", "prepaid": true}

    Requests must carry ``X-Signature: hex(hmac_sha256(AGGREGATOR_WEBHOOK_SECRET, body))``.
    """
    r = _restaurant(slug)
    from apps.superadmin.models import get_settings

    secret = get_settings().aggregator_webhook_secret or settings.AGGREGATOR_WEBHOOK_SECRET
    sig = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest() if secret else None
    if not secret or not hmac.compare_digest(sig, request.headers.get("X-Signature", "")):
        return Response({"detail": "bad signature"}, status=401)
    if not r.has_feature("aggregators"):
        return Response({"detail": "Aggregator sync requires the Pro plan"}, status=403)
    src = source if source in ("swiggy", "zomato") else "other"
    d = request.data
    if Order.objects.filter(restaurant=r, source=src, external_id=d.get("external_id")).exists():
        return Response({"detail": "duplicate"}, status=200)
    from apps.menu.models import Item

    items = []
    for i in d.get("items", []):
        it = Item.objects.filter(restaurant=r, pk=i.get("item_id")).first() if i.get("item_id") else Item.objects.filter(restaurant=r, name__iexact=i.get("name", "")).first()
        if it:
            items.append({"item_id": it.id, "quantity": i.get("quantity", 1), "price": i.get("price"), "notes": i.get("notes", "")})
    c = d.get("customer", {})
    try:
        order = services.create_order(r, order_type="delivery" if d.get("type", "delivery") == "delivery" else "takeaway", source=src,
                                      customer_name=c.get("name", ""), customer_phone=c.get("phone", ""), delivery_address=c.get("address", ""),
                                      notes=d.get("notes", ""), items=items, external_id=d.get("external_id", ""),
                                      payment_mode="online" if d.get("prepaid", True) else "cod")
        if d.get("prepaid", True):
            services.add_payment(order, "wallet", order.total, reference=f"{src}:{d.get('external_id')}")
    except services.OrderError as e:
        return Response({"detail": str(e)}, status=400)
    return Response({"order": order.number, "status": order.status}, status=201)
