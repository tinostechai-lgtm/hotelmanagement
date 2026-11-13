"""Business logic for orders, KOTs, billing and payments.

Every interface (web POS, Flutter app, QR ordering, online store, aggregator
webhooks) goes through these functions so behaviour is identical everywhere.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.crm.models import Coupon, Customer
from apps.menu.models import Addon, Item, Variant

from .models import KOT, Bill, Counter, Notification, Order, OrderItem, Payment, Table, money


class OrderError(Exception):
    pass


class TableBusy(OrderError):
    """Another attendant is serving this table (HTTP 409)."""


class DuplicateItems(OrderError):
    """The same items were just added to this order by someone else (HTTP 409; resend with confirm_duplicate)."""


DUPLICATE_WINDOW_SECONDS = 180


def batch_signature(items):
    """Order-independent fingerprint of a batch of items (item, qty, variant, add-ons, notes)."""
    import hashlib
    import json

    norm = sorted(
        (int(s.get("item_id") or 0), str(Decimal(str(s.get("quantity", 1))).normalize()), int(s.get("variant_id") or 0),
         sorted(int(a) for a in (s.get("addon_ids") or [])), (s.get("notes") or "").strip().lower())
        for s in items if Decimal(str(s.get("quantity", 1))) > 0
    )
    return hashlib.sha1(json.dumps(norm).encode()).hexdigest()


def _staff_name(user):
    return str(user).strip() or "another attendant"


def table_busy_reason(table, user, device=""):
    """Why `user` (on `device`) may not take orders on `table` right now, or None if they may.

    Attendant A holds a table while it is open on their phone/tab and while its running order is theirs;
    attendant B is blocked until A is done. The hold is per device, so two phones sharing one login can't
    both work the same table. Customer QR orders (no user) are never blocked."""
    if user is None or table is None:
        return None
    holder = table.live_lock
    if holder is not None and holder.pk != user.pk:
        return f"Table {table.name} is being served by {_staff_name(holder)} right now."
    if holder is not None and device and table.locked_device and table.locked_device != device:
        return (f"Table {table.name} is open on another phone or tab (signed in as {_staff_name(holder)}). "
                f"Close it there first, or wait a minute.")
    o = table.active_order
    if o and o.taken_by_id and o.taken_by_id != user.pk:
        return f"Table {table.name} already has an order taken by {_staff_name(o.taken_by)}. Ask them or a manager."
    return None


def check_table_access(table, user, can_override=False, device=""):
    if can_override:
        return
    reason = table_busy_reason(table, user, device)
    if reason:
        raise TableBusy(reason)


def get_or_create_customer(restaurant, phone, name="", email=""):
    phone = (phone or "").strip()
    if not phone:
        return None
    c, created = Customer.objects.get_or_create(restaurant=restaurant, phone=phone, defaults={"name": name, "email": email})
    if not created and ((name and not c.name) or (email and not c.email)):
        c.name = c.name or name
        c.email = c.email or email
        c.save()
    return c


def _already_applied(restaurant, ref):
    """The order a request with this idempotency key already created or added items to (None if new)."""
    if not ref:
        return None
    order = Order.objects.filter(restaurant=restaurant, client_ref=ref).first()
    if order:
        return order
    line = OrderItem.objects.filter(order__restaurant=restaurant, batch_ref=ref).select_related("order").first()
    return line.order if line else None


@transaction.atomic
def create_order(restaurant, *, order_type="dine_in", source="pos", table=None, room=None, user=None,
                 customer_phone="", customer_name="", guests=1, notes="", items=None, status=None,
                 delivery_address="", delivery_lat=None, delivery_lng=None, coupon_code="", payment_mode="",
                 external_id="", customer_email="", client_ref="", can_override=False, device="",
                 confirm_duplicate=False):
    if table is not None:
        # One request at a time per table: two devices (or a double tap) can't both see "no open order"
        # and each start one.
        table = Table.objects.select_for_update().get(pk=table.pk)
    dup = _already_applied(restaurant, client_ref)
    if dup:
        return dup  # re-sent request (retry, offline replay, double click): don't add anything again
    if table is not None and order_type == "dine_in" and source in ("pos", "captain"):
        check_table_access(table, user, can_override, device)  # one attendant (and one device) per table
    if table is not None and order_type == "dine_in":
        existing = table.active_order
        if existing and source in ("pos", "captain", "qr"):
            if items:
                add_items(existing, items, batch_ref=client_ref, user=user,
                          check_duplicate=source in ("pos", "captain") and not confirm_duplicate)
            return existing
    customer = get_or_create_customer(restaurant, customer_phone, customer_name, customer_email)
    if status is None:
        status = "pending" if source in ("qr", "online", "app", "swiggy", "zomato", "other") else "accepted"
    order = Order.objects.create(
        restaurant=restaurant, order_type=order_type, source=source, table=table, room=room, taken_by=user,
        customer=customer, customer_name=customer_name or (customer.name if customer else ""),
        customer_phone=customer_phone, guests=guests or 1, notes=notes, status=status,
        delivery_address=delivery_address, delivery_lat=delivery_lat, delivery_lng=delivery_lng,
        payment_mode=payment_mode, external_id=external_id, client_ref=client_ref,
        accepted_at=timezone.now() if status == "accepted" else None,
    )
    if coupon_code:
        apply_coupon(order, coupon_code, save=False)
    if table is not None:
        table.status = Table.Status.OCCUPIED
        table.occupied_since = table.occupied_since or timezone.now()
        table.save(update_fields=["status", "occupied_since"])
    if items:
        add_items(order, items, batch_ref=client_ref, user=user)
    else:
        order.recalc()
    if source not in ("pos", "captain") and payment_mode != "online":
        Notification.objects.create(restaurant=restaurant, kind="new_order",
                                    title=f"New {order.get_source_display()} order #{order.number}",
                                    body=f"{order.label} · ₹{order.total}", link=f"/app/orders/{order.pk}/")
    if order_type == "delivery":
        from apps.delivery.services import ensure_delivery_task

        ensure_delivery_task(order)
    return order


@transaction.atomic
def add_items(order, items, batch_ref="", user=None, check_duplicate=False):
    """items: [{item_id, quantity, variant_id?, addon_ids?, notes?, seat?, price?}]

    batch_ref: idempotency key of the request. Re-sending the same batch adds nothing."""
    if order.pk:
        # Lock the order row so concurrent adds to the same order run one after another.
        order.status = Order.objects.select_for_update().only("status").get(pk=order.pk).status
    if batch_ref and order.items.filter(batch_ref=batch_ref).exists():
        return []
    sig = batch_signature(items) if items else ""
    if check_duplicate and sig:
        # Two crew entering the same table's order: the very same items again within a few minutes.
        since = timezone.now() - timedelta(seconds=DUPLICATE_WINDOW_SECONDS)
        prev = (order.items.filter(batch_sig=sig, is_void=False, created_at__gte=since)
                .exclude(batch_ref=batch_ref or "\x00").select_related("added_by").order_by("-created_at").first())
        if prev:
            who = _staff_name(prev.added_by) if prev.added_by_id else "someone"
            mins = int((timezone.now() - prev.created_at).total_seconds() // 60)
            ago = "just now" if mins < 1 else f"{mins} min ago"
            raise DuplicateItems(f"These items were already added to this order by {who} ({ago}). "
                                 f"If the guest really ordered them again, choose 'Add again'.")
    if order.status in ("completed", "cancelled"):
        raise OrderError("Order is closed")
    restaurant = order.restaurant
    created = []
    for spec in items:
        item = Item.objects.filter(restaurant=restaurant, pk=spec.get("item_id")).select_related("hsn").first()
        if not item:
            raise OrderError(f"Unknown item {spec.get('item_id')}")
        qty = Decimal(str(spec.get("quantity", 1)))
        if qty <= 0:
            continue
        if not item.in_stock:
            raise OrderError(f"{item.name} is currently unavailable")
        if item.track_stock and item.stock_qty < qty:
            raise OrderError(f"Only {item.stock_qty} left of {item.name}")
        price = item.delivery_price if (order.order_type == "delivery" and item.delivery_price) else item.price
        variant_name = ""
        if spec.get("variant_id"):
            v = Variant.objects.filter(item=item, pk=spec["variant_id"]).first()
            if v:
                price, variant_name = v.price, v.name
        if spec.get("price") is not None and order.source in ("swiggy", "zomato", "other"):
            price = Decimal(str(spec["price"]))
        addons = [{"id": a.pk, "name": a.name, "price": str(a.price)}
                  for a in Addon.objects.filter(pk__in=spec.get("addon_ids") or [], group__restaurant=restaurant, is_available=True)]
        li = OrderItem.objects.create(order=order, item=item, name=item.name, variant_name=variant_name, addons=addons,
                                      quantity=qty, unit_price=price, tax_percent=restaurant.tax_rate_for(item),
                                      notes=spec.get("notes", "")[:160], seat=spec.get("seat"), batch_ref=batch_ref[:64],
                                      batch_sig=sig, added_by=user)
        if item.track_stock:
            item.stock_qty -= int(qty)
            if item.stock_qty <= 0:
                item.is_available = False
            item.save(update_fields=["stock_qty", "is_available"])
        created.append(li)
    order.recalc()
    return created


def update_item(order_item, quantity=None, notes=None):
    if quantity is not None:
        q = Decimal(str(quantity))
        if q <= 0:
            return void_item(order_item, "Removed")
        if order_item.status != "new" and q < order_item.quantity:
            raise OrderError("Item already sent to kitchen — void it instead")
        order_item.quantity = q
    if notes is not None:
        order_item.notes = notes
    order_item.save()
    order_item.order.recalc()
    return order_item


def void_item(order_item, reason=""):
    order_item.is_void = True
    order_item.void_reason = reason
    order_item.save()
    if order_item.item and order_item.item.track_stock:
        order_item.item.stock_qty += int(order_item.quantity)
        order_item.item.save(update_fields=["stock_qty"])
    order_item.order.recalc()
    return order_item


@transaction.atomic
def send_kot(order, print_now=True):
    """Group unsent lines by kitchen station into KOTs and queue printing."""
    pending = order.items.filter(is_void=False, status="new", kot__isnull=True).select_related("item__station", "item__category__station")
    groups = defaultdict(list)
    for li in pending:
        station = li.item.kitchen_station() if li.item else None
        groups[station].append(li)
    kots = []
    for station, lines in groups.items():
        kot = KOT.objects.create(restaurant=order.restaurant, order=order, station=station,
                                 number=Counter.next(order.restaurant, "kot"))
        OrderItem.objects.filter(pk__in=[li.pk for li in lines]).update(kot=kot, status="sent")
        kots.append(kot)
        if print_now:
            from apps.hardware.services import print_kot

            print_kot(kot)
    if kots and order.status == "pending":
        order.set_status("accepted")
    if kots and order.status in ("served", "ready") and order.order_type == "dine_in":
        order.status = "preparing"
        order.save(update_fields=["status"])
    return kots


def apply_coupon(order, code, save=True):
    coupon = Coupon.objects.filter(restaurant=order.restaurant, code__iexact=code.strip()).first()
    if not coupon:
        raise OrderError("Invalid coupon code")
    order.recalc(save=False)
    _, err = coupon.discount_for(order.subtotal)
    if err:
        raise OrderError(err)
    order.coupon = coupon
    order.discount_reason = f"Coupon {coupon.code}"
    if save:
        order.recalc()
    return order


def apply_discount(order, amount=None, percent=None, reason=""):
    order.coupon = None
    order.recalc(save=False)
    if percent is not None:
        amount = order.subtotal * Decimal(str(percent)) / 100
    order.discount = money(min(Decimal(str(amount or 0)), order.subtotal))
    order.discount_reason = reason or (f"{percent}% off" if percent else "Manual discount")
    return order.recalc()


def _bill_lines(items, ratio=Decimal("1")):
    return [{"name": li.display_name, "qty": f"{(li.quantity * ratio).normalize():f}",
             "rate": str(li.unit_price + li.addons_total), "amount": str(money(li.line_total * ratio)),
             "tax": str(li.tax_percent)} for li in items]


def _new_bill_number(restaurant):
    n = Counter.next(restaurant, "bill", daily=False)
    return f"INV-{timezone.localdate():%y%m}-{n:05d}"


@transaction.atomic
def generate_bill(order, customer_gstin=""):
    """Create (or refresh) the single unpaid bill for the order."""
    order.recalc()
    if not order.live_items().exists():
        raise OrderError("Cannot bill an empty order")
    bill = order.bills.exclude(status="void").first()
    if bill and bill.status != "unpaid" and order.bills.exclude(status="void").count() > 1:
        return bill
    if bill is None:
        bill = Bill(restaurant=order.restaurant, order=order, number=_new_bill_number(order.restaurant))
    bill.subtotal, bill.discount, bill.service_charge = order.subtotal, order.discount, order.service_charge
    bill.tax, bill.round_off, bill.total = order.tax, order.round_off, order.total
    bill.extra_charges = order.delivery_fee + order.packaging_charge + order.tip
    bill.lines = _bill_lines(order.live_items())
    bill.customer_gstin = customer_gstin or bill.customer_gstin
    bill.save()
    bill.refresh_paid()
    if order.table_id:
        order.table.status = Table.Status.BILLED
        order.table.save(update_fields=["status"])
    return bill


@transaction.atomic
def split_bill(order, mode="equal", parts=2, groups=None):
    """Split an order into multiple bills.

    mode="equal": ``parts`` equal bills.
    mode="items": ``groups`` = [[order_item_id, ...], ...]
    mode="seat":  one bill per seat number on the lines.
    """
    order.recalc()
    order.bills.filter(status="unpaid").update(status="void")
    if order.bills.exclude(status="void").exists():
        raise OrderError("A bill on this order already has payments; void it first")
    items = list(order.live_items())
    if mode == "seat":
        by_seat = defaultdict(list)
        for li in items:
            by_seat[li.seat or 0].append(li.pk)
        groups = list(by_seat.values())
        mode = "items"
    bills = []
    if mode == "equal":
        parts = max(2, int(parts))
        share = money(order.total / parts)
        for i in range(parts):
            last = i == parts - 1
            total = order.total - share * (parts - 1) if last else share
            ratio = Decimal(1) / parts
            b = Bill.objects.create(
                restaurant=order.restaurant, order=order, number=_new_bill_number(order.restaurant), label=f"Split {i + 1}/{parts}",
                subtotal=money(order.subtotal * ratio), discount=money(order.discount * ratio),
                service_charge=money(order.service_charge * ratio), tax=money(order.tax * ratio),
                extra_charges=money((order.delivery_fee + order.packaging_charge + order.tip) * ratio),
                total=total, lines=_bill_lines(items, ratio))
            b.round_off = money(b.total - (b.subtotal - b.discount + b.service_charge + b.tax + b.extra_charges))
            b.save()
            bills.append(b)
    elif mode == "items":
        groups = [g for g in (groups or []) if g]
        assigned = {int(i) for g in groups for i in g}
        rest = [li.pk for li in items if li.pk not in assigned]
        if rest:
            groups.append(rest)
        r = order.restaurant
        disc_ratio = (order.subtotal - order.discount) / order.subtotal if order.subtotal else Decimal("1")
        for idx, g in enumerate(groups, 1):
            lines = [li for li in items if li.pk in {int(x) for x in g}]
            if not lines:
                continue
            sub = sum((li.line_total for li in lines), Decimal("0"))
            disc = sub - sub * disc_ratio
            tax = sum((li.line_total * disc_ratio * li.tax_percent / 100 for li in lines), Decimal("0"))
            if r.includes_tax:
                tax = sum((li.line_total * disc_ratio - li.line_total * disc_ratio / (1 + li.tax_percent / 100) for li in lines), Decimal("0"))
            if not r.gst_enabled:
                tax = Decimal("0")
            svc = (sub - disc) * r.service_charge_percent / 100 if order.order_type == "dine_in" else Decimal("0")
            gross = sub - disc + svc + (Decimal("0") if r.includes_tax else tax)
            total = gross.quantize(Decimal("1")) if r.round_off_bills else money(gross)
            bills.append(Bill.objects.create(
                restaurant=r, order=order, number=_new_bill_number(r), label=f"Split {idx}/{len(groups)}",
                subtotal=money(sub), discount=money(disc), service_charge=money(svc), tax=money(tax),
                round_off=money(total - gross), total=money(total), lines=_bill_lines(lines)))
    else:
        raise OrderError("Unknown split mode")
    if order.table_id:
        order.table.status = Table.Status.BILLED
        order.table.save(update_fields=["status"])
    return bills


@transaction.atomic
def add_payment(order, method, amount, bill=None, reference="", user=None, tendered=None, status="success", razorpay_order_id=""):
    amount = money(Decimal(str(amount)))
    if amount <= 0:
        raise OrderError("Amount must be positive")
    if bill is None:
        bill = order.bills.exclude(status__in=["void", "paid"]).first() or generate_bill(order)
    if method == "room" and not order.room_id:
        raise OrderError("Room posting needs a room on the order")
    if method == "loyalty":
        c = order.customer
        if not c or c.loyalty_points < int(amount):
            raise OrderError("Not enough loyalty points")
        c.loyalty_points -= int(amount)
        c.save(update_fields=["loyalty_points"])
    p = Payment.objects.create(restaurant=order.restaurant, order=order, bill=bill, method=method, amount=amount,
                               reference=reference, received_by=user, tendered=tendered, status=status,
                               razorpay_order_id=razorpay_order_id)
    if status == "success":
        _after_payment(order, bill)
    return p


def _after_payment(order, bill):
    if bill is None:
        bill = generate_bill(order)
        order.payments.filter(bill__isnull=True).update(bill=bill)
    bill.refresh_paid()
    paid = sum((p.amount for p in order.payments.filter(status="success")), Decimal("0"))
    order.paid_amount = paid
    order.is_paid = paid >= order.total
    order.save(update_fields=["paid_amount", "is_paid"])
    if not order.is_paid or order.status in ("completed", "cancelled", "pending"):
        return
    # Dine-in bills are paid at the end of the meal; prepaid takeaway / online
    # orders stay open until the kitchen marks them ready.
    if order.status in ("served", "ready", "delivered") or (order.order_type == "dine_in" and order.source in ("pos", "captain")):
        settle_order(order)


def confirm_payment(payment, reference=""):
    payment.status = "success"
    payment.reference = reference or payment.reference
    payment.save()
    _after_payment(payment.order, payment.bill)
    order = payment.order
    if order.status == "pending" and order.source in ("online", "app", "qr"):
        Notification.objects.create(restaurant=order.restaurant, kind="new_order", title=f"New prepaid {order.get_source_display()} order #{order.number}",
                                    body=f"{order.label} · ₹{payment.amount} paid via Razorpay", link=f"/app/orders/{order.pk}/")
    return payment


def awaiting_payment(qs):
    """Online orders whose customer hasn't finished Razorpay checkout yet."""
    return qs.filter(status="pending", payment_mode="online", is_paid=False)


def expire_unpaid_online_orders(restaurant):
    """Cancel online orders left unpaid at checkout (called lazily from polling)."""
    from datetime import timedelta

    from django.conf import settings

    cutoff = timezone.now() - timedelta(minutes=settings.UNPAID_ONLINE_ORDER_TTL_MINUTES)
    stale = awaiting_payment(Order.objects.filter(restaurant=restaurant, created_at__lt=cutoff))
    for order in stale:
        order.payments.filter(status="pending").update(status="failed")
        cancel_order(order, "Payment not completed")
    return len(stale)


@transaction.atomic
def settle_order(order, user=None):
    """Close the order: deduct inventory, award loyalty, free the table."""
    if order.status == "completed":
        return order
    from apps.inventory.services import consume_for_order

    consume_for_order(order)
    if order.customer:
        order.customer.record_visit(order.total)
    if order.coupon_id:
        Coupon.objects.filter(pk=order.coupon_id).update(used_count=order.coupon.used_count + 1)
    order.items.filter(is_void=False).update(status="served")
    order.kots.exclude(status="cancelled").update(status="served")
    if order.status not in ("completed",):
        order.status = "served" if order.status not in ("delivered",) else order.status
        order.save(update_fields=["status"])
        order.set_status("completed", user)
    return order


def cancel_order(order, reason, user=None):
    if order.status in ("completed", "cancelled"):
        raise OrderError("Order already closed")
    for li in order.items.filter(is_void=False):
        if li.item and li.item.track_stock:
            li.item.stock_qty += int(li.quantity)
            li.item.save(update_fields=["stock_qty"])
    order.kots.update(status="cancelled")
    order.bills.filter(status="unpaid").update(status="void")
    order.status = "accepted" if order.status == "served" else order.status
    order.set_status("cancelled", user, reason)
    if hasattr(order, "delivery"):
        order.delivery.status = "failed"
        order.delivery.failure_reason = reason
        order.delivery.save()
    return order


def move_table(order, new_table):
    old = order.table
    if new_table.active_order and new_table.active_order != order:
        # merge into the target table's order
        target = new_table.active_order
        order.items.update(order=target)
        order.kots.update(order=target)
        target.recalc()
        order.status = "cancelled"
        order.cancel_reason = f"Merged into #{target.number}"
        order.save()
        result = target
    else:
        order.table = new_table
        order.save(update_fields=["table"])
        new_table.status = Table.Status.OCCUPIED
        new_table.occupied_since = old.occupied_since if old else timezone.now()
        new_table.save()
        result = order
    if old and not old.orders.filter(status__in=Order.OPEN_STATUSES).exists():
        old.status = Table.Status.FREE
        old.occupied_since = None
        old.save()
    return result
