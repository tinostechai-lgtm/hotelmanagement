from rest_framework.decorators import action
from rest_framework.response import Response

from apps.tenants.api_base import TenantViewSet

from .models import AddonGroup, Category, HSNCode, Item, KitchenStation
from .serializers import AddonGroupSerializer, CategorySerializer, HSNSerializer, ItemSerializer, StationSerializer


class CategoryViewSet(TenantViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    perm = "menu"


class ItemViewSet(TenantViewSet):
    queryset = Item.objects.select_related("category", "hsn").prefetch_related("variants", "addon_groups__addons")
    serializer_class = ItemSerializer
    perm = "menu"

    def perform_update(self, serializer):
        from apps.accounts.models import AuditLog

        old = serializer.instance.price
        item = serializer.save()
        if item.price != old:
            AuditLog.record(item.restaurant, self.request.user, "menu.price", item.name, f"₹{old} → ₹{item.price}")

    def perform_destroy(self, instance):
        from apps.accounts.models import AuditLog

        AuditLog.record(instance.restaurant, self.request.user, "menu.delete", instance.name, f"₹{instance.price}")
        instance.delete()

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("category"):
            qs = qs.filter(category_id=p["category"])
        if p.get("q"):
            from django.db.models import Q

            q = p["q"]
            qs = qs.filter(Q(name__icontains=q) | Q(short_code__iexact=q) | Q(barcode=q))
        return qs

    @action(detail=True, methods=["post"], url_path="toggle")
    def toggle(self, request, pk=None):
        """Real-time availability (86 / un-86 an item). Allowed for POS staff too."""
        item = self.get_object()
        item.is_available = not item.is_available if "available" not in request.data else bool(request.data["available"])
        item.save(update_fields=["is_available"])
        return Response({"id": item.id, "is_available": item.is_available})

    def get_permissions(self):
        if self.action == "toggle":
            from rest_framework.permissions import IsAuthenticated

            from apps.accounts.permissions import HasRestaurant
            return [IsAuthenticated(), HasRestaurant()]
        return super().get_permissions()


class AddonGroupViewSet(TenantViewSet):
    queryset = AddonGroup.objects.prefetch_related("addons")
    serializer_class = AddonGroupSerializer
    perm = "menu"


class HSNViewSet(TenantViewSet):
    queryset = HSNCode.objects.all()
    serializer_class = HSNSerializer
    perm = "menu"


class StationViewSet(TenantViewSet):
    queryset = KitchenStation.objects.all()
    serializer_class = StationSerializer
    perm = "menu"


def menu_payload(restaurant, online=False):
    """Compact full-menu payload for POS / apps / storefront."""
    cats = Category.objects.filter(restaurant=restaurant, is_active=True)
    items = Item.objects.filter(restaurant=restaurant).select_related("hsn").prefetch_related("variants", "addon_groups__addons")
    if online:
        items = items.filter(available_online=True)
    out = []
    by_cat = {}
    for it in items:
        by_cat.setdefault(it.category_id, []).append({
            "id": it.id, "name": it.name, "description": it.description, "price": str(it.delivery_price or it.price) if online else str(it.price),
            "dine_in_price": str(it.price), "image_url": it.image_url, "diet": it.diet, "short_code": it.short_code, "barcode": it.barcode,
            "tax_percent": str(it.effective_tax), "available": it.in_stock, "bestseller": it.is_bestseller, "is_weighted": it.is_weighted,
            "spice_level": it.spice_level, "prep_minutes": it.prep_minutes,
            "variants": [{"id": v.id, "name": v.name, "price": str(v.price)} for v in it.variants.all()],
            "addon_groups": [{"id": g.id, "name": g.name, "min": g.min_select, "max": g.max_select,
                              "addons": [{"id": a.id, "name": a.name, "price": str(a.price)} for a in g.addons.all() if a.is_available]}
                             for g in it.addon_groups.all()],
        })
    for c in cats:
        if by_cat.get(c.id):
            out.append({"id": c.id, "name": c.name, "image_url": c.image_url, "items": by_cat[c.id]})
    return out
