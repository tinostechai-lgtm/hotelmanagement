from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import AuditLog
from apps.tenants.api_base import TenantViewSet

from . import services
from .models import KOT, Area, Bill, Notification, Order, OrderItem, Reservation, Room, Shift, Table
from .serializers import (AreaSerializer, BillHistorySerializer, BillSerializer, LiveOrderSerializer, CreateOrderSerializer, KOTSerializer, LineSpec,
                          NotificationSerializer, OrderListSerializer, OrderSerializer, ReservationSerializer,
                          RoomSerializer, ShiftSerializer, TableSerializer)


def _err(e):
    if isinstance(e, services.DuplicateItems):
        return Response({"detail": str(e), "code": "duplicate_items"}, status=status.HTTP_409_CONFLICT)
    code = status.HTTP_409_CONFLICT if isinstance(e, services.TableBusy) else status.HTTP_400_BAD_REQUEST
    return Response({"detail": str(e), "code": "table_busy" if code == 409 else "error"}, status=code)


def _device(request):
    """Id of the phone / browser tab making the request (X-Device-Id header; empty for old apps)."""
    return (request.headers.get("X-Device-Id") or "")[:64]


class AreaViewSet(TenantViewSet):
    queryset = Area.objects.all()
    serializer_class = AreaSerializer
    perm = "tables"


class TableViewSet(TenantViewSet):
    queryset = Table.objects.select_related("area")
    serializer_class = TableSerializer
    perm = "tables"

    @action(detail=True, methods=["post"])
    def status(self, request, pk=None):
        t = self.get_object()
        new = request.data.get("status")
        if new not in Table.Status.values:
            return _err("Invalid status")
        t.status = new
        t.save(update_fields=["status"])
        return Response(TableSerializer(t).data)

    @action(detail=True, methods=["post"])
    def lock(self, request, pk=None):
        """Hold the table while it is open on this device (call again every ~30 s to keep it)."""
        with transaction.atomic():
            t = Table.objects.select_for_update().get(pk=self.get_object().pk)
            reason = services.table_busy_reason(t, request.user, _device(request))
            if reason and not (request.data.get("take_over") and request.membership.can("void")):
                return Response({"detail": reason, "code": "table_busy", "can_take_over": request.membership.can("void")}, status=409)
            if reason:  # manager takes the table over: the running order is now theirs
                o = t.active_order
                if o and o.taken_by_id != request.user.pk:
                    prev = services._staff_name(o.taken_by) if o.taken_by else "-"
                    o.taken_by = request.user
                    o.save(update_fields=["taken_by"])
                    AuditLog.record(t.restaurant, request.user, "table.take_over", f"Table {t.name}", f"#{o.number} from {prev}")
            t.locked_by, t.locked_at, t.locked_device = request.user, timezone.now(), _device(request)
            t.save(update_fields=["locked_by", "locked_at", "locked_device"])
        return Response(TableSerializer(t).data)

    @action(detail=True, methods=["post"])
    def unlock(self, request, pk=None):
        qs = Table.objects.filter(pk=self.get_object().pk, locked_by=request.user)
        if _device(request):
            qs = qs.filter(locked_device__in=[_device(request), ""])  # don't release another phone's hold
        qs.update(locked_by=None, locked_at=None, locked_device="")
        return Response({"ok": True})

    def get_permissions(self):
        if self.action in ("status", "lock", "unlock"):
            return self._member_perms()
        return super().get_permissions()

    def _member_perms(self):
        from rest_framework.permissions import IsAuthenticated

        from apps.accounts.permissions import HasRestaurant
        return [IsAuthenticated(), HasRestaurant()]


class RoomViewSet(TenantViewSet):
    queryset = Room.objects.all()
    serializer_class = RoomSerializer
    perm = "tables"
    feature = "room_service"

    @action(detail=True, methods=["post"])
    def checkout(self, request, pk=None):
        """Guest checks out: return F&B folio and free the room."""
        room = self.get_object()
        orders = room.orders.filter(created_at__gte=room.checked_in_at or timezone.now() - timedelta(days=30))
        folio = [{"order": o.number, "date": o.created_at, "total": str(o.total),
                  "posted_to_room": str(sum((p.amount for p in o.payments.filter(method="room", status="success")), Decimal("0")))}
                 for o in orders]
        room.is_occupied, room.guest_name, room.guest_phone, room.checked_in_at, room.pms_reference = False, "", "", None, ""
        room.save()
        return Response({"room": room.number, "folio": folio})

    @action(detail=True, methods=["post"])
    def checkin(self, request, pk=None):
        room = self.get_object()
        room.is_occupied = True
        room.guest_name = request.data.get("guest_name", "")
        room.guest_phone = request.data.get("guest_phone", "")
        room.pms_reference = request.data.get("pms_reference", "")
        room.checked_in_at = timezone.now()
        room.save()
        return Response(RoomSerializer(room).data)


class ReservationViewSet(TenantViewSet):
    queryset = Reservation.objects.select_related("table")
    serializer_class = ReservationSerializer
    perm = "pos"


class OrderViewSet(TenantViewSet):
    queryset = Order.objects.select_related("table", "room", "customer", "restaurant").prefetch_related("items", "bills__payments", "payments", "kots__station")
    serializer_class = OrderSerializer
    perm = "pos"
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_serializer_class(self):
        return OrderListSerializer if self.action == "list" else OrderSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("status") in ("open", "pending") and not p.get("include_unpaid"):
            qs = qs.exclude(pk__in=services.awaiting_payment(qs).values("pk"))
        if p.get("status") == "open":
            qs = qs.filter(status__in=Order.OPEN_STATUSES)
        elif p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("type"):
            qs = qs.filter(order_type__in=p["type"].split(","))
        if p.get("source"):
            qs = qs.filter(source__in=p["source"].split(","))
        if p.get("date"):
            qs = qs.filter(created_at__date=p["date"])
        if p.get("q"):
            q = p["q"]
            qs = qs.filter(Q(number__icontains=q) | Q(customer_phone__icontains=q) | Q(customer_name__icontains=q))
        if p.get("since"):
            qs = qs.filter(updated_at__gt=p["since"])
        return qs

    def create(self, request, *args, **kwargs):
        s = CreateOrderSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        r = request.restaurant
        table = get_object_or_404(Table, restaurant=r, pk=d["table"]) if d.get("table") else None
        room = get_object_or_404(Room, restaurant=r, pk=d["room"]) if d.get("room") else None
        try:
            order = services.create_order(
                r, order_type=d["order_type"], source=d["source"], table=table, room=room, user=request.user,
                customer_phone=d["customer_phone"], customer_name=d["customer_name"], guests=d["guests"], notes=d["notes"],
                items=[dict(i) for i in d.get("items", [])], delivery_address=d["delivery_address"],
                delivery_lat=d.get("delivery_lat"), delivery_lng=d.get("delivery_lng"), client_ref=d["client_ref"],
                can_override=request.membership.can("void"), device=_device(request),
                confirm_duplicate=bool(request.data.get("confirm_duplicate")),
                payment_mode="cod" if d["order_type"] == "delivery" else "")
            if d["send_kot"]:
                services.send_kot(order)
        except services.OrderError as e:
            return _err(e)
        order.refresh_from_db()
        return Response(OrderSerializer(order).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        order = self.get_object()
        for f in ("customer_name", "customer_phone", "guests", "notes", "delivery_address", "tip"):
            if f in request.data:
                setattr(order, f, request.data[f])
        if request.data.get("customer_phone"):
            order.customer = services.get_or_create_customer(order.restaurant, request.data["customer_phone"], request.data.get("customer_name", ""))
        order.save()
        order.recalc()
        return Response(OrderSerializer(order).data)

    def _ok(self, order):
        order.refresh_from_db()
        return Response(OrderSerializer(order).data)

    @action(detail=False)
    def live(self, request):
        """Lightweight poll endpoint for dashboards / apps (no websockets needed on Vercel)."""
        r = request.restaurant
        services.expire_unpaid_online_orders(r)
        qs = Order.objects.filter(restaurant=r, status__in=Order.OPEN_STATUSES)
        qs = qs.exclude(pk__in=services.awaiting_payment(qs).values("pk"))
        return Response({
            "server_time": timezone.now(),
            "orders": (LiveOrderSerializer(qs.select_related("table", "taken_by").prefetch_related("items")[:200], many=True).data
                       if request.query_params.get("details") else OrderListSerializer(qs[:200], many=True).data),
            "pending_online": qs.filter(status="pending").count(),
            "unread_notifications": Notification.objects.filter(restaurant=r, is_read=False).count(),
        })

    @action(detail=True, methods=["post"], url_path="items")
    def add_items(self, request, pk=None):
        order = self.get_object()
        s = LineSpec(data=request.data.get("items", []), many=True)
        s.is_valid(raise_exception=True)
        try:
            if order.table_id and order.order_type == "dine_in":
                services.check_table_access(order.table, request.user, request.membership.can("void"), _device(request))
            services.add_items(order, [dict(i) for i in s.validated_data], batch_ref=str(request.data.get("client_ref") or "")[:64],
                               user=request.user, check_duplicate=not request.data.get("confirm_duplicate"))
            if request.data.get("send_kot"):
                services.send_kot(order)
        except services.OrderError as e:
            return _err(e)
        return self._ok(order)

    @action(detail=True, methods=["post"], url_path=r"items/(?P<line_id>\d+)")
    def update_item(self, request, pk=None, line_id=None):
        order = self.get_object()
        li = get_object_or_404(OrderItem, order=order, pk=line_id)
        try:
            if request.data.get("void"):
                if li.status != "new" and not request.membership.can("void"):
                    return Response({"detail": "Only managers can void items sent to kitchen"}, status=403)
                services.void_item(li, request.data.get("reason", ""))
                AuditLog.record(order.restaurant, request.user, "order.void_item", f"#{order.number}",
                                f"{li.quantity.normalize():f} × {li.display_name} (₹{li.line_total}) — {request.data.get('reason', '')}")
            else:
                services.update_item(li, request.data.get("quantity"), request.data.get("notes"))
        except services.OrderError as e:
            return _err(e)
        return self._ok(order)

    @action(detail=True, methods=["post"])
    def kot(self, request, pk=None):
        order = self.get_object()
        kots = services.send_kot(order, print_now=request.data.get("print", True))
        if not kots:
            return _err("No new items to send")
        return self._ok(order)

    @action(detail=True, methods=["post"])
    def status(self, request, pk=None):
        order = self.get_object()
        try:
            new = request.data.get("status")
            if new == "cancelled":
                if not request.membership.can("void") and order.status != "pending":
                    return Response({"detail": "Only managers can cancel accepted orders"}, status=403)
                services.cancel_order(order, request.data.get("reason", "Cancelled"), request.user)
                AuditLog.record(order.restaurant, request.user, "order.cancel", f"#{order.number}",
                                f"₹{order.total} — {request.data.get('reason', '')}")
            elif new == "completed":
                services.settle_order(order, request.user)
            else:
                order.set_status(new, request.user)
                if new == "accepted" and request.data.get("send_kot", True):
                    services.send_kot(order)
        except (ValueError, services.OrderError) as e:
            return _err(e)
        return self._ok(order)

    @action(detail=True, methods=["post"])
    def discount(self, request, pk=None):
        order = self.get_object()
        if not request.membership.can("discount"):
            return Response({"detail": "Discount permission required"}, status=403)
        try:
            if request.data.get("coupon"):
                services.apply_coupon(order, request.data["coupon"])
            else:
                services.apply_discount(order, request.data.get("amount"), request.data.get("percent"), request.data.get("reason", ""))
        except services.OrderError as e:
            return _err(e)
        AuditLog.record(order.restaurant, request.user, "order.discount", f"#{order.number}",
                        f"₹{order.discount} off — {order.discount_reason}")
        return self._ok(order)

    @action(detail=True, methods=["post"])
    def bill(self, request, pk=None):
        order = self.get_object()
        try:
            bill = services.generate_bill(order, request.data.get("customer_gstin", ""))
            if request.data.get("print", True):
                from apps.hardware.services import print_bill

                print_bill(bill)
        except services.OrderError as e:
            return _err(e)
        return self._ok(order)

    @action(detail=True, methods=["post"])
    def split(self, request, pk=None):
        order = self.get_object()
        if not order.restaurant.has_feature("split_bill"):
            return Response({"detail": "Split billing is available on Growth and above."}, status=403)
        try:
            services.split_bill(order, request.data.get("mode", "equal"), request.data.get("parts", 2), request.data.get("groups"))
        except services.OrderError as e:
            return _err(e)
        return self._ok(order)

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        """Body: {payments: [{method, amount, reference?, tendered?, bill?}]} or a single payment."""
        order = self.get_object()
        entries = request.data.get("payments") or [request.data]
        try:
            for e in entries:
                bill = get_object_or_404(Bill, order=order, pk=e["bill"]) if e.get("bill") else None
                services.add_payment(order, e.get("method", "cash"), e.get("amount", order.balance), bill=bill,
                                     reference=e.get("reference", ""), user=request.user, tendered=e.get("tendered"))
        except services.OrderError as e:
            return _err(e)
        if request.data.get("open_drawer") or any(e.get("method") == "cash" for e in entries):
            from apps.hardware.services import open_drawer

            open_drawer(order.restaurant)
        return self._ok(order)

    @action(detail=True, methods=["post"], url_path="move")
    def move(self, request, pk=None):
        order = self.get_object()
        table = get_object_or_404(Table, restaurant=request.restaurant, pk=request.data.get("table"))
        target = services.move_table(order, table)
        return self._ok(target)

    @action(detail=True, methods=["post"], url_path="print")
    def print_bill(self, request, pk=None):
        from apps.hardware.services import print_bill

        order = self.get_object()
        bills = order.bills.exclude(status="void")
        if not bills:
            return _err("Generate the bill first")
        jobs = [j for b in bills for j in print_bill(b)]
        return Response({"queued": len(jobs), "preview": jobs[0].text if jobs else ""})


class KOTViewSet(TenantViewSet):
    """Kitchen display. GET /api/kots/?status=pending,preparing&station=1"""

    queryset = KOT.objects.select_related("order__table", "order__room", "station").prefetch_related("lines")
    serializer_class = KOTSerializer
    perm = "kitchen"
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        statuses = (p.get("status") or "pending,preparing,ready").split(",")
        qs = qs.filter(status__in=statuses)
        if p.get("station"):
            qs = qs.filter(station_id=p["station"])
        if "ready" in statuses:
            qs = qs.filter(Q(status__in=["pending", "preparing"]) | Q(ready_at__gte=timezone.now() - timedelta(hours=2)))
        return qs.order_by("created_at")

    def create(self, request, *args, **kwargs):
        return Response(status=405)

    @action(detail=True, methods=["post"])
    def status(self, request, pk=None):
        kot = self.get_object()
        new = request.data.get("status")
        if new not in KOT.Status.values:
            return _err("Invalid status")
        kot.set_status(new)
        return Response(KOTSerializer(kot).data)

    @action(detail=True, methods=["post"])
    def reprint(self, request, pk=None):
        from apps.hardware.services import print_kot

        print_kot(self.get_object())
        return Response({"ok": True})


class NotificationViewSet(TenantViewSet):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    http_method_names = ["get", "post", "head", "options"]

    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        self.get_queryset().update(is_read=True)
        return Response({"ok": True})


class ShiftViewSet(TenantViewSet):
    queryset = Shift.objects.all()
    serializer_class = ShiftSerializer
    perm = read_perm = "shifts"
    http_method_names = ["get", "post", "head", "options"]

    def perform_create(self, serializer):
        serializer.save(restaurant=self.request.restaurant, opened_by=self.request.user)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        from .models import Payment

        shift = self.get_object()
        cash = sum((p.amount for p in Payment.objects.filter(restaurant=shift.restaurant, method__in=["cash", "cod"], status="success",
                                                             created_at__gte=shift.created_at)), Decimal("0"))
        shift.expected_cash = shift.opening_cash + cash
        shift.closing_cash = Decimal(str(request.data.get("closing_cash", 0)))
        shift.closed_at = timezone.now()
        shift.notes = request.data.get("notes", "")
        shift.save()
        AuditLog.record(shift.restaurant, request.user, "shift.close", f"Shift {shift.pk}",
                        f"expected ₹{shift.expected_cash}, counted ₹{shift.closing_cash}, difference ₹{shift.closing_cash - shift.expected_cash}")
        return Response(ShiftSerializer(shift).data)


class BillViewSet(TenantViewSet):
    """Bill history: find, view and reprint bills - including after they are paid."""
    queryset = Bill.objects.select_related("order", "order__taken_by", "order__table").prefetch_related("payments")
    serializer_class = BillHistorySerializer
    perm = "pos"
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset().exclude(status="void").order_by("-created_at")
        p = self.request.query_params
        if p.get("date"):
            qs = qs.filter(created_at__date=p["date"])
        if p.get("start"):
            qs = qs.filter(created_at__date__gte=p["start"])
        if p.get("end"):
            qs = qs.filter(created_at__date__lte=p["end"])
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("q"):
            q = p["q"].strip()
            qs = qs.filter(Q(number__icontains=q) | Q(order__number__icontains=q) | Q(order__customer_phone__icontains=q)
                           | Q(order__customer_name__icontains=q) | Q(order__table__name__iexact=q))
        return qs

    def create(self, request, *args, **kwargs):
        return Response({"detail": "Bills are created from orders"}, status=405)

    @action(detail=True, methods=["post"], url_path="print")
    def print_bill(self, request, pk=None):
        """Reprint a bill (works after payment). Returns the receipt text for an on-screen preview."""
        from apps.hardware.services import print_bill, render_bill

        bill = self.get_object()
        jobs = print_bill(bill) if request.data.get("to_printer", True) else []
        return Response({"queued": len(jobs), "preview": render_bill(bill).plain})
