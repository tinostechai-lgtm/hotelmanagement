import secrets
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.tenants.models import Restaurant, TenantModel

TWO = Decimal("0.01")


def money(v):
    return Decimal(v).quantize(TWO, rounding=ROUND_HALF_UP)


class Area(TenantModel):
    """Floor section: Indoor, Patio, Rooftop, AC Hall …"""

    name = models.CharField(max_length=60)
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort", "name"]

    def __str__(self):
        return self.name


class Table(TenantModel):
    class Status(models.TextChoices):
        FREE = "free", "Available"
        OCCUPIED = "occupied", "Occupied"
        BILLED = "billed", "Bill printed"
        RESERVED = "reserved", "Reserved"
        CLEANING = "cleaning", "Cleaning"

    area = models.ForeignKey(Area, null=True, blank=True, on_delete=models.SET_NULL, related_name="tables")
    name = models.CharField(max_length=20)
    seats = models.PositiveSmallIntegerField(default=4)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.FREE)
    shape = models.CharField(max_length=10, default="square")  # square / round / long
    pos_x = models.PositiveIntegerField(default=0)
    pos_y = models.PositiveIntegerField(default=0)
    qr_token = models.CharField(max_length=24, unique=True, editable=False)
    occupied_since = models.DateTimeField(null=True, blank=True)
    # Who has this table open on their POS / app right now (renewed while the screen is open).
    locked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    locked_at = models.DateTimeField(null=True, blank=True)

    LOCK_SECONDS = 90

    class Meta:
        ordering = ["area__sort", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.qr_token:
            self.qr_token = secrets.token_urlsafe(12)
        super().save(*args, **kwargs)

    @property
    def active_order(self):
        return self.orders.filter(status__in=Order.OPEN_STATUSES).order_by("-created_at").first()

    @property
    def live_lock(self):
        """The user who has this table open right now (None if nobody, or the lock has expired)."""
        from datetime import timedelta

        from django.utils import timezone

        if self.locked_by_id and self.locked_at and self.locked_at > timezone.now() - timedelta(seconds=self.LOCK_SECONDS):
            return self.locked_by
        return None


class Room(TenantModel):
    """Hotel rooms for room service and posting F&B charges to the guest folio."""

    number = models.CharField(max_length=10)
    room_type = models.CharField(max_length=40, blank=True)
    floor = models.CharField(max_length=10, blank=True)
    guest_name = models.CharField(max_length=120, blank=True)
    guest_phone = models.CharField(max_length=20, blank=True)
    is_occupied = models.BooleanField(default=False)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    pms_reference = models.CharField(max_length=60, blank=True, help_text="Folio / reservation id in your PMS")
    qr_token = models.CharField(max_length=24, unique=True, editable=False)

    class Meta:
        ordering = ["number"]

    def __str__(self):
        return f"Room {self.number}"

    def save(self, *args, **kwargs):
        if not self.qr_token:
            self.qr_token = secrets.token_urlsafe(12)
        super().save(*args, **kwargs)


class Counter(models.Model):
    """Per-restaurant, per-day running numbers for orders / KOTs / bills."""

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE)
    key = models.CharField(max_length=20)
    day = models.DateField()
    value = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("restaurant", "key", "day")

    @classmethod
    def next(cls, restaurant, key, daily=True):
        day = timezone.localdate() if daily else timezone.datetime(2000, 1, 1).date()
        with transaction.atomic():
            c, _ = cls.objects.select_for_update().get_or_create(restaurant=restaurant, key=key, day=day)
            c.value += 1
            c.save(update_fields=["value"])
            return c.value


class Order(TenantModel):
    class Type(models.TextChoices):
        DINE_IN = "dine_in", "Dine-in"
        TAKEAWAY = "takeaway", "Takeaway"
        DELIVERY = "delivery", "Home delivery"
        ROOM_SERVICE = "room_service", "Room service"

    class Source(models.TextChoices):
        POS = "pos", "POS"
        CAPTAIN = "captain", "Captain app"
        QR = "qr", "QR table order"
        ONLINE = "online", "Online store"
        APP = "app", "Customer app"
        SWIGGY = "swiggy", "Swiggy"
        ZOMATO = "zomato", "Zomato"
        OTHER = "other", "Other aggregator"

    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting acceptance"
        ACCEPTED = "accepted", "Accepted"
        PREPARING = "preparing", "Preparing"
        READY = "ready", "Ready"
        SERVED = "served", "Served"
        OUT_FOR_DELIVERY = "out_for_delivery", "Out for delivery"
        DELIVERED = "delivered", "Delivered"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    OPEN_STATUSES = ["pending", "accepted", "preparing", "ready", "served", "out_for_delivery", "delivered"]
    FLOW = {
        "pending": ["accepted", "cancelled"],
        "accepted": ["preparing", "ready", "cancelled"],
        "preparing": ["ready", "cancelled"],
        "ready": ["served", "out_for_delivery", "completed", "cancelled"],
        "served": ["completed", "preparing"],
        "out_for_delivery": ["delivered", "cancelled"],
        "delivered": ["completed"],
        "completed": [],
        "cancelled": [],
    }

    number = models.CharField(max_length=20)
    order_type = models.CharField(max_length=14, choices=Type.choices, default=Type.DINE_IN)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.POS)
    status = models.CharField(max_length=18, choices=Status.choices, default=Status.ACCEPTED)
    table = models.ForeignKey(Table, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    room = models.ForeignKey(Room, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    customer = models.ForeignKey("crm.Customer", null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    customer_name = models.CharField(max_length=120, blank=True)
    customer_phone = models.CharField(max_length=20, blank=True)
    guests = models.PositiveSmallIntegerField(default=1)
    notes = models.CharField(max_length=255, blank=True)
    taken_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    # Delivery
    delivery_address = models.TextField(blank=True)
    delivery_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    delivery_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    external_id = models.CharField(max_length=60, blank=True, help_text="Aggregator order id")
    client_ref = models.CharField(max_length=64, blank=True, db_index=True, help_text="Idempotency key from offline apps")

    # Money (snapshot, recalculated by recalc())
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_reason = models.CharField(max_length=80, blank=True)
    coupon = models.ForeignKey("crm.Coupon", null=True, blank=True, on_delete=models.SET_NULL)
    service_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    packaging_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tip = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    round_off = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_paid = models.BooleanField(default=False)
    payment_mode = models.CharField(max_length=12, blank=True, help_text="Intended mode for online orders (cod/online)")

    tracking_token = models.CharField(max_length=24, unique=True, editable=False)
    cancel_reason = models.CharField(max_length=200, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["restaurant", "status"]), models.Index(fields=["restaurant", "created_at"])]

    def __str__(self):
        return f"#{self.number}"

    def save(self, *args, **kwargs):
        if not self.tracking_token:
            self.tracking_token = secrets.token_urlsafe(12)
        if not self.number:
            n = Counter.next(self.restaurant, "order")
            self.number = f"{timezone.localdate():%d%m}-{n:03d}"
        super().save(*args, **kwargs)

    @property
    def balance(self):
        return max(Decimal("0"), self.total - self.paid_amount)

    @property
    def label(self):
        if self.table_id:
            return f"Table {self.table.name}"
        if self.room_id:
            return f"Room {self.room.number}"
        return self.get_order_type_display()

    def live_items(self):
        return self.items.filter(is_void=False)

    def recalc(self, save=True):
        r = self.restaurant
        subtotal = Decimal("0")
        tax = Decimal("0")
        lines = list(self.live_items())
        for li in lines:
            subtotal += li.line_total
        if self.coupon_id:
            d, err = self.coupon.discount_for(subtotal)
            self.discount = d if not err else Decimal("0")
        discount = min(self.discount, subtotal)
        ratio = (subtotal - discount) / subtotal if subtotal else Decimal("0")
        for li in lines if r.gst_enabled else []:  # GST off: no tax at all
            taxable = li.line_total * ratio
            if r.includes_tax:
                tax += taxable - taxable / (1 + li.tax_percent / 100)
            else:
                tax += taxable * li.tax_percent / 100
        net = subtotal - discount
        service = net * r.service_charge_percent / 100 if self.order_type == self.Type.DINE_IN else Decimal("0")
        if self.order_type == self.Type.DELIVERY:
            if self.source not in (self.Source.SWIGGY, self.Source.ZOMATO, self.Source.OTHER):
                free = r.free_delivery_above and net >= r.free_delivery_above
                self.delivery_fee = Decimal("0") if free else r.delivery_fee
        else:
            self.delivery_fee = Decimal("0")
        self.packaging_charge = r.packaging_charge if self.order_type in (self.Type.DELIVERY, self.Type.TAKEAWAY) and lines else Decimal("0")
        gross = net + service + (Decimal("0") if r.includes_tax else tax) + self.delivery_fee + self.packaging_charge + self.tip
        total = gross.quantize(Decimal("1"), rounding=ROUND_HALF_UP) if r.round_off_bills else money(gross)
        self.subtotal, self.discount, self.service_charge, self.tax = money(subtotal), money(discount), money(service), money(tax)
        self.round_off = money(total - gross)
        self.total = money(total)
        self.is_paid = self.paid_amount >= self.total and self.total > 0
        if save:
            self.save()
        return self

    def tax_breakup(self):
        """GST split by rate: {rate: (taxable, cgst, sgst)}. Empty when the restaurant doesn't charge GST."""
        if not self.restaurant.gst_enabled:
            return {}
        out = {}
        ratio = (self.subtotal - self.discount) / self.subtotal if self.subtotal else Decimal("0")
        for li in self.live_items():
            taxable = li.line_total * ratio
            if self.restaurant.includes_tax:
                taxable = taxable / (1 + li.tax_percent / 100)
            t = taxable * li.tax_percent / 100
            row = out.setdefault(li.tax_percent, [Decimal("0"), Decimal("0")])
            row[0] += taxable
            row[1] += t
        return {k: {"taxable": money(v[0]), "cgst": money(v[1] / 2), "sgst": money(v[1] / 2)} for k, v in out.items()}

    def set_status(self, new_status, user=None, reason=""):
        if new_status == self.status:
            return
        if new_status not in self.FLOW.get(self.status, []):
            raise ValueError(f"Cannot move order from {self.status} to {new_status}")
        now = timezone.now()
        self.status = new_status
        if new_status == "accepted":
            self.accepted_at = now
        elif new_status == "ready":
            self.ready_at = now
        elif new_status in ("completed",):
            self.completed_at = now
        elif new_status == "cancelled":
            self.cancel_reason = reason
        self.save()
        if self.table_id and new_status in ("completed", "cancelled"):
            t = self.table
            if not t.orders.filter(status__in=self.OPEN_STATUSES).exclude(pk=self.pk).exists():
                t.status = Table.Status.CLEANING if new_status == "completed" else Table.Status.FREE
                t.occupied_since = None
                t.save(update_fields=["status", "occupied_since"])
        OrderEvent.objects.create(order=self, status=new_status, by=user, note=reason)
        if self.source in (self.Source.ONLINE, self.Source.APP, self.Source.QR) and new_status in ("accepted", "out_for_delivery", "delivered"):
            from apps.superadmin.messaging import notify_customer

            transaction.on_commit(lambda: notify_customer(self, new_status))


class OrderItem(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Not sent"
        SENT = "sent", "Sent to kitchen"
        PREPARING = "preparing", "Preparing"
        READY = "ready", "Ready"
        SERVED = "served", "Served"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey("menu.Item", null=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=160)
    variant_name = models.CharField(max_length=60, blank=True)
    addons = models.JSONField(default=list, blank=True)  # [{"name":..., "price":...}]
    quantity = models.DecimalField(max_digits=8, decimal_places=3, default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    notes = models.CharField(max_length=160, blank=True)
    seat = models.PositiveSmallIntegerField(null=True, blank=True)
    batch_ref = models.CharField(max_length=64, blank=True, db_index=True,
                                 help_text="Idempotency key of the request that added this line (blocks duplicate re-sends)")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW)
    kot = models.ForeignKey("KOT", null=True, blank=True, on_delete=models.SET_NULL, related_name="lines")
    is_void = models.BooleanField(default=False)
    void_reason = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.quantity} x {self.name}"

    @property
    def addons_total(self):
        return sum((Decimal(str(a.get("price", 0))) for a in self.addons), Decimal("0"))

    @property
    def line_total(self):
        return money((self.unit_price + self.addons_total) * self.quantity)

    @property
    def display_name(self):
        return f"{self.name} ({self.variant_name})" if self.variant_name else self.name


class OrderEvent(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    status = models.CharField(max_length=18)
    note = models.CharField(max_length=200, blank=True)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at"]


class KOT(TenantModel):
    class Status(models.TextChoices):
        PENDING = "pending", "New"
        PREPARING = "preparing", "Preparing"
        READY = "ready", "Ready"
        SERVED = "served", "Picked up"
        CANCELLED = "cancelled", "Cancelled"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="kots")
    number = models.PositiveIntegerField()
    station = models.ForeignKey("menu.KitchenStation", null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    printed = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"KOT {self.number}"

    def set_status(self, status):
        now = timezone.now()
        self.status = status
        if status == "preparing":
            self.started_at = now
        if status == "ready":
            self.ready_at = now
        self.save()
        line_status = {"preparing": "preparing", "ready": "ready", "served": "served"}.get(status)
        if line_status:
            self.lines.update(status=line_status)
        # Roll up to order status.
        order = self.order
        kots = order.kots.exclude(status="cancelled")
        if order.status in ("accepted", "preparing") and status == "preparing":
            order.set_status("preparing")
        if kots.exists() and all(k.status in ("ready", "served") for k in kots) and order.status in ("accepted", "preparing"):
            order.set_status("ready")


class Bill(TenantModel):
    """Final tax invoice. An order normally has one bill; split billing creates several."""

    class Status(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PARTIAL = "partial", "Partially paid"
        PAID = "paid", "Paid"
        VOID = "void", "Void"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="bills")
    number = models.CharField(max_length=24)
    label = models.CharField(max_length=40, blank=True, help_text="e.g. 'Split 1/3' or 'Seat 2'")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    service_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    extra_charges = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    round_off = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.UNPAID)
    lines = models.JSONField(default=list)
    customer_gstin = models.CharField(max_length=15, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.number

    @property
    def balance(self):
        return max(Decimal("0"), self.total - self.paid)

    def refresh_paid(self):
        self.paid = sum((p.amount for p in self.payments.filter(status="success")), Decimal("0"))
        if self.status != self.Status.VOID:
            if self.paid >= self.total:
                self.status = self.Status.PAID
                self.settled_at = self.settled_at or timezone.now()
            elif self.paid > 0:
                self.status = self.Status.PARTIAL
        self.save()


class Payment(TenantModel):
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        UPI = "upi", "UPI"
        RAZORPAY = "razorpay", "Razorpay (online)"
        ROOM = "room", "Post to room"
        WALLET = "wallet", "Wallet / Paytm"
        COD = "cod", "Cash on delivery"
        LOYALTY = "loyalty", "Loyalty points"
        CREDIT = "credit", "Credit / Due"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments")
    bill = models.ForeignKey(Bill, null=True, blank=True, on_delete=models.CASCADE, related_name="payments")
    method = models.CharField(max_length=10, choices=Method.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    tendered = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    reference = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=10, default="success")  # pending / success / failed / refunded
    razorpay_order_id = models.CharField(max_length=40, blank=True, db_index=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    @property
    def change_due(self):
        return max(Decimal("0"), (self.tendered or self.amount) - self.amount)


class Notification(TenantModel):
    kind = models.CharField(max_length=20, default="info")  # new_order / low_stock / delivery / info
    title = models.CharField(max_length=120)
    body = models.CharField(max_length=255, blank=True)
    link = models.CharField(max_length=200, blank=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]


class Reservation(TenantModel):
    customer_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20)
    guests = models.PositiveSmallIntegerField(default=2)
    reserved_for = models.DateTimeField()
    table = models.ForeignKey(Table, null=True, blank=True, on_delete=models.SET_NULL)
    notes = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, default="booked")  # booked / seated / no_show / cancelled

    class Meta:
        ordering = ["reserved_for"]


class Shift(TenantModel):
    """Cash-drawer shift for day-end reconciliation."""

    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    opening_cash = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    closing_cash = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    expected_cash = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]
