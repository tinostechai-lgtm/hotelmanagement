"""Sales analytics + lightweight forecasting ("smart insights")."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, F, Sum
from django.db.models.functions import ExtractHour, TruncDate
from django.utils import timezone

from .models import Order, OrderItem, Payment


def _range(start=None, end=None, days=None):
    today = timezone.localdate()
    if days:
        return today - timedelta(days=days - 1), today
    return start or today, end or start or today


def summary(restaurant, start=None, end=None):
    start, end = _range(start, end)
    orders = Order.objects.filter(restaurant=restaurant, created_at__date__gte=start, created_at__date__lte=end)
    done = orders.filter(status="completed")
    agg = done.aggregate(sales=Sum("total"), tax=Sum("tax"), discount=Sum("discount"), n=Count("id"), guests=Sum("guests"),
                         delivery=Sum("delivery_fee"), service=Sum("service_charge"))
    sales = agg["sales"] or Decimal("0")
    n = agg["n"] or 0
    pays = Payment.objects.filter(restaurant=restaurant, status="success", created_at__date__gte=start, created_at__date__lte=end)
    lines = OrderItem.objects.filter(order__in=done, is_void=False)
    top_items = (lines.values("name").annotate(qty=Sum("quantity"), amount=Sum(F("quantity") * F("unit_price")))
                 .order_by("-qty")[:10])
    by_cat = (lines.values("item__category__name").annotate(amount=Sum(F("quantity") * F("unit_price"))).order_by("-amount"))
    hourly = done.annotate(h=ExtractHour("created_at")).values("h").annotate(sales=Sum("total"), n=Count("id")).order_by("h")
    daily = done.annotate(d=TruncDate("created_at")).values("d").annotate(sales=Sum("total"), n=Count("id")).order_by("d")
    return {
        "start": start, "end": end,
        "sales": sales, "orders": n, "avg_order_value": (sales / n).quantize(Decimal("0.01")) if n else Decimal("0"),
        "tax": agg["tax"] or 0, "discount": agg["discount"] or 0, "guests": agg["guests"] or 0,
        "delivery_fees": agg["delivery"] or 0, "service_charge": agg["service"] or 0,
        "cancelled": orders.filter(status="cancelled").count(),
        "open_orders": orders.filter(status__in=Order.OPEN_STATUSES).count(),
        "by_payment": list(pays.values("method").annotate(amount=Sum("amount"), n=Count("id")).order_by("-amount")),
        "by_type": list(done.values("order_type").annotate(amount=Sum("total"), n=Count("id")).order_by("-amount")),
        "by_source": list(done.values("source").annotate(amount=Sum("total"), n=Count("id")).order_by("-amount")),
        "top_items": [{"name": t["name"], "qty": t["qty"], "amount": t["amount"]} for t in top_items],
        "by_category": [{"name": c["item__category__name"] or "Other", "amount": c["amount"]} for c in by_cat],
        "hourly": [{"hour": h["h"], "sales": h["sales"], "orders": h["n"]} for h in hourly],
        "daily": [{"date": d["d"], "sales": d["sales"], "orders": d["n"]} for d in daily],
    }


def insights(restaurant):
    """Forecast next 7 days with weekday-weighted moving average, plus
    plain-English recommendations. No external ML service required."""
    today = timezone.localdate()
    start = today - timedelta(days=56)
    rows = (Order.objects.filter(restaurant=restaurant, status="completed", created_at__date__gte=start)
            .annotate(d=TruncDate("created_at")).values("d").annotate(s=Sum("total"), n=Count("id")))
    by_day = {r["d"]: r for r in rows}
    weekday = defaultdict(list)
    for i in range(56):
        d = start + timedelta(days=i)
        weekday[d.weekday()].append(float(by_day.get(d, {}).get("s") or 0))
    forecast = []
    for i in range(1, 8):
        d = today + timedelta(days=i)
        hist = weekday[d.weekday()][-4:]
        weights = [1, 2, 3, 4][-len(hist):] if hist else []
        val = sum(h * w for h, w in zip(hist, weights)) / sum(weights) if weights else 0
        forecast.append({"date": d, "weekday": d.strftime("%a"), "expected_sales": round(val, 2)})
    tips = []
    s30 = summary(restaurant, today - timedelta(days=29), today)
    s_prev = summary(restaurant, today - timedelta(days=59), today - timedelta(days=30))
    if s_prev["sales"]:
        growth = (float(s30["sales"]) - float(s_prev["sales"])) / float(s_prev["sales"]) * 100
        tips.append(f"Sales are {'up' if growth >= 0 else 'down'} {abs(growth):.0f}% vs the previous 30 days.")
    if s30["hourly"]:
        peak = max(s30["hourly"], key=lambda h: h["sales"] or 0)
        tips.append(f"Your peak hour is {peak['hour']:02d}:00 — schedule extra staff and pre-prep for it.")
    if s30["top_items"]:
        tips.append(f"'{s30['top_items'][0]['name']}' is your best seller — feature it on the QR menu and online store.")
    sold = {t["name"] for t in s30["top_items"]}
    from apps.menu.models import Item

    slow = Item.objects.filter(restaurant=restaurant, is_available=True).exclude(name__in=sold).exclude(
        orderitem__order__created_at__date__gte=today - timedelta(days=29)).values_list("name", flat=True)[:3]
    if slow:
        tips.append("Slow movers in the last 30 days: " + ", ".join(slow) + ". Consider a combo or removing them.")
    online = sum(float(x["amount"] or 0) for x in s30["by_source"] if x["source"] in ("online", "app", "qr"))
    if s30["sales"] and online / float(s30["sales"]) < 0.15:
        tips.append("Less than 15% of sales come from QR/online. Print table QR codes and share your store link on WhatsApp.")
    from apps.inventory.models import Ingredient

    low = [i.name for i in Ingredient.objects.filter(restaurant=restaurant) if i.is_low]
    if low:
        tips.append("Re-order soon: " + ", ".join(low[:5]) + ".")
    return {"forecast": forecast, "next_7_days_total": round(sum(f["expected_sales"] for f in forecast), 2), "tips": tips}
