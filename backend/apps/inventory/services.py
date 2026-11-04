from apps.operations.models import Notification

from .models import RecipeLine, StockMovement


def consume_for_order(order):
    """Deduct recipe ingredients for every sold item and raise low-stock alerts."""
    low = set()
    for li in order.items.filter(is_void=False).select_related("item"):
        if not li.item_id:
            continue
        for rl in RecipeLine.objects.filter(item_id=li.item_id).select_related("ingredient"):
            ing = rl.ingredient
            StockMovement.record(ing, "consumption", -(rl.quantity * li.quantity), f"Order {order.number}")
            if ing.is_low:
                low.add(ing)
    for ing in low:
        Notification.objects.get_or_create(
            restaurant=order.restaurant, kind="low_stock", title=f"Low stock: {ing.name}", is_read=False,
            defaults={"body": f"{ing.stock} {ing.unit} left (reorder at {ing.reorder_level})", "link": "/app/inventory/"})
