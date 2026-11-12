from rest_framework import serializers

from apps.tenants.api_base import TenantSerializer

from .models import KOT, Area, Bill, Notification, Order, OrderItem, Payment, Reservation, Room, Shift, Table


class AreaSerializer(TenantSerializer):
    class Meta:
        model = Area
        exclude = ["restaurant"]


class TableSerializer(TenantSerializer):
    area_name = serializers.CharField(source="area.name", read_only=True, default="")
    active_order = serializers.SerializerMethodField()
    in_use_by = serializers.SerializerMethodField()

    class Meta:
        model = Table
        exclude = ["restaurant", "locked_by", "locked_at"]
        read_only_fields = ["qr_token", "occupied_since"]

    def get_in_use_by(self, t):
        """Attendant who has the table open right now: {id, name} or None."""
        u = t.live_lock
        return {"id": u.pk, "name": str(u)} if u else None

    def get_active_order(self, t):
        o = t.active_order
        if not o:
            return None
        return {"id": o.id, "number": o.number, "total": str(o.total), "status": o.status, "guests": o.guests,
                "items": o.live_items().count(), "since": o.created_at, "is_paid": o.is_paid,
                "taken_by": ({"id": o.taken_by_id, "name": str(o.taken_by)} if o.taken_by_id else None),
                "billed": o.bills.exclude(status="void").exists()}


class RoomSerializer(TenantSerializer):
    open_charges = serializers.SerializerMethodField()

    class Meta:
        model = Room
        exclude = ["restaurant"]
        read_only_fields = ["qr_token"]

    def get_open_charges(self, room):
        from django.db.models import Sum

        return str(room.orders.filter(payments__method="room", payments__status="success").aggregate(s=Sum("payments__amount"))["s"] or 0)


class ReservationSerializer(TenantSerializer):
    class Meta:
        model = Reservation
        exclude = ["restaurant"]


class OrderItemSerializer(serializers.ModelSerializer):
    line_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = OrderItem
        exclude = ["order"]


class KOTSerializer(serializers.ModelSerializer):
    lines = OrderItemSerializer(many=True, read_only=True)
    order_number = serializers.CharField(source="order.number", read_only=True)
    order_label = serializers.CharField(source="order.label", read_only=True)
    order_type = serializers.CharField(source="order.order_type", read_only=True)
    order_notes = serializers.CharField(source="order.notes", read_only=True)
    station_name = serializers.CharField(source="station.name", read_only=True, default="")
    source = serializers.CharField(source="order.source", read_only=True)

    class Meta:
        model = KOT
        exclude = ["restaurant"]


class PaymentSerializer(serializers.ModelSerializer):
    method_display = serializers.CharField(source="get_method_display", read_only=True)

    class Meta:
        model = Payment
        exclude = ["restaurant"]


class BillSerializer(serializers.ModelSerializer):
    payments = PaymentSerializer(many=True, read_only=True)
    balance = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Bill
        exclude = ["restaurant"]


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    kots = serializers.SerializerMethodField()
    bills = BillSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    label = serializers.CharField(read_only=True)
    balance = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    table_name = serializers.CharField(source="table.name", read_only=True, default=None)
    room_number = serializers.CharField(source="room.number", read_only=True, default=None)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    source_display = serializers.CharField(source="get_source_display", read_only=True)
    type_display = serializers.CharField(source="get_order_type_display", read_only=True)
    next_statuses = serializers.SerializerMethodField()
    delivery = serializers.SerializerMethodField()
    tax_breakup = serializers.SerializerMethodField()

    class Meta:
        model = Order
        exclude = ["restaurant"]

    def get_kots(self, o):
        return [{"id": k.id, "number": k.number, "status": k.status, "station": k.station.name if k.station else ""} for k in o.kots.all()]

    def get_next_statuses(self, o):
        return Order.FLOW.get(o.status, [])

    def get_tax_breakup(self, o):
        return {str(k): {kk: str(vv) for kk, vv in v.items()} for k, v in o.tax_breakup().items()}

    def get_delivery(self, o):
        d = getattr(o, "delivery", None)
        if not d:
            return None
        return {"id": d.id, "status": d.status, "rider": d.rider.name if d.rider else None, "rider_phone": d.rider.phone if d.rider else None,
                "rider_id": d.rider_id, "distance_km": d.distance_km, "eta_minutes": d.eta_minutes, "otp": d.otp,
                "cod_amount": str(d.cod_amount), "rider_lat": d.rider.latitude if d.rider else None, "rider_lng": d.rider.longitude if d.rider else None}


class OrderListSerializer(serializers.ModelSerializer):
    label = serializers.CharField(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    source_display = serializers.CharField(source="get_source_display", read_only=True)
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ["id", "number", "order_type", "source", "source_display", "status", "status_display", "label", "customer_name",
                  "customer_phone", "total", "paid_amount", "is_paid", "created_at", "item_count", "table", "room", "payment_mode"]

    def get_item_count(self, o):
        return o.items.filter(is_void=False).count()


class LineSpec(serializers.Serializer):
    item_id = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=8, decimal_places=3, default=1)
    variant_id = serializers.IntegerField(required=False, allow_null=True)
    addon_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    seat = serializers.IntegerField(required=False, allow_null=True)


class CreateOrderSerializer(serializers.Serializer):
    order_type = serializers.ChoiceField(choices=Order.Type.choices, default="dine_in")
    source = serializers.ChoiceField(choices=[("pos", "POS"), ("captain", "Captain")], default="pos")
    table = serializers.IntegerField(required=False, allow_null=True)
    room = serializers.IntegerField(required=False, allow_null=True)
    customer_phone = serializers.CharField(required=False, allow_blank=True, default="")
    customer_name = serializers.CharField(required=False, allow_blank=True, default="")
    guests = serializers.IntegerField(required=False, default=1)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    delivery_address = serializers.CharField(required=False, allow_blank=True, default="")
    delivery_lat = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    delivery_lng = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    items = LineSpec(many=True, required=False)
    send_kot = serializers.BooleanField(default=False)
    client_ref = serializers.CharField(required=False, allow_blank=True, default="", help_text="Offline idempotency key")


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        exclude = ["restaurant"]


class ShiftSerializer(serializers.ModelSerializer):
    opened_by_name = serializers.CharField(source="opened_by.__str__", read_only=True)

    class Meta:
        model = Shift
        exclude = ["restaurant"]
        read_only_fields = ["opened_by", "expected_cash", "closed_at"]
