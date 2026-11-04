from decimal import Decimal

from django.utils import timezone

from .models import DeliveryTask, DeliveryZone, Rider, Settlement, haversine_km


def quote(restaurant, lat=None, lng=None, pincode="", subtotal=Decimal("0")):
    """Return {serviceable, distance_km, fee, eta_minutes, min_order, message}."""
    dist = haversine_km(restaurant.latitude, restaurant.longitude, lat, lng)
    zones = DeliveryZone.objects.filter(restaurant=restaurant, is_active=True)
    zone = None
    if pincode:
        zone = next((z for z in zones if pincode in [p.strip() for p in z.pincodes.split(",") if p.strip()]), None)
    if zone is None and dist is not None:
        zone = next((z for z in zones if dist <= float(z.max_km)), None)
    if dist is not None and dist > float(restaurant.delivery_radius_km) and zone is None:
        return {"serviceable": False, "distance_km": dist, "message": f"Sorry, we deliver within {restaurant.delivery_radius_km} km"}
    fee = zone.fee if zone else restaurant.delivery_fee
    min_order = zone.min_order if zone else restaurant.delivery_min_order
    if restaurant.free_delivery_above and subtotal >= restaurant.free_delivery_above:
        fee = Decimal("0")
    eta = (zone.eta_minutes if zone else restaurant.avg_prep_minutes + int((dist or 3) * 4))
    return {"serviceable": True, "distance_km": dist, "fee": fee, "eta_minutes": eta, "min_order": min_order,
            "zone": zone.name if zone else None, "message": ""}


def ensure_delivery_task(order):
    task, _ = DeliveryTask.objects.get_or_create(order=order, defaults={"restaurant": order.restaurant})
    task.distance_km = haversine_km(order.restaurant.latitude, order.restaurant.longitude, order.delivery_lat, order.delivery_lng)
    q = quote(order.restaurant, order.delivery_lat, order.delivery_lng, subtotal=order.subtotal)
    task.eta_minutes = q.get("eta_minutes") or 35
    task.cod_amount = order.total if order.payment_mode in ("cod", "") and not order.is_paid else Decimal("0")
    task.save()
    return task


def auto_assign(task):
    """Pick the nearest online rider with the fewest active deliveries."""
    riders = Rider.objects.filter(restaurant=task.restaurant, is_active=True, is_online=True)
    if not riders:
        return None
    r = task.restaurant

    def score(rider):
        d = haversine_km(r.latitude, r.longitude, rider.latitude, rider.longitude) or 0
        return (rider.active_tasks.count(), d)

    rider = sorted(riders, key=score)[0]
    task.assign(rider)
    return rider


def settle_rider(rider, user=None, notes=""):
    tasks = list(rider.tasks.filter(status="delivered", settlement__isnull=True))
    cash = sum((t.cod_collected for t in tasks), Decimal("0"))
    s = Settlement.objects.create(restaurant=rider.restaurant, rider=rider, cash_collected=cash,
                                  rider_payout=rider.per_delivery_pay * len(tasks), deliveries=len(tasks),
                                  settled_by=user, notes=notes)
    DeliveryTask.objects.filter(pk__in=[t.pk for t in tasks]).update(settlement=s)
    for t in tasks:
        o = t.order
        if t.cod_collected and not o.is_paid:
            from apps.operations.services import add_payment

            add_payment(o, "cod", t.cod_collected, reference=f"Settlement {s.pk}", user=user)
        if o.status == "delivered":
            from apps.operations.services import settle_order

            settle_order(o, user)
    return s


def ping(rider, lat, lng):
    from .models import RiderPing

    rider.latitude, rider.longitude, rider.last_seen = lat, lng, timezone.now()
    rider.is_online = True
    rider.save(update_fields=["latitude", "longitude", "last_seen", "is_online"])
    task = rider.tasks.filter(status__in=["accepted", "picked_up"]).first()
    RiderPing.objects.create(rider=rider, task=task, latitude=lat, longitude=lng)
