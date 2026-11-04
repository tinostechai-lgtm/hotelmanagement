from rest_framework import serializers

from apps.tenants.api_base import TenantSerializer

from .models import Addon, AddonGroup, Category, HSNCode, Item, KitchenStation, Variant


class HSNSerializer(TenantSerializer):
    class Meta:
        model = HSNCode
        exclude = ["restaurant"]


class StationSerializer(TenantSerializer):
    class Meta:
        model = KitchenStation
        exclude = ["restaurant"]


class CategorySerializer(TenantSerializer):
    item_count = serializers.IntegerField(source="items.count", read_only=True)

    class Meta:
        model = Category
        exclude = ["restaurant"]


class VariantSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = Variant
        fields = ["id", "name", "price"]


class AddonSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = Addon
        fields = ["id", "name", "price", "is_available"]


class AddonGroupSerializer(TenantSerializer):
    addons = AddonSerializer(many=True, required=False)

    class Meta:
        model = AddonGroup
        exclude = ["restaurant"]

    def _save_addons(self, group, addons):
        if addons is None:
            return
        keep = []
        for a in addons:
            obj, _ = Addon.objects.update_or_create(group=group, pk=a.get("id"), defaults={k: v for k, v in a.items() if k != "id"})
            keep.append(obj.pk)
        group.addons.exclude(pk__in=keep).delete()

    def create(self, data):
        addons = data.pop("addons", [])
        g = super().create(data)
        self._save_addons(g, addons)
        return g

    def update(self, inst, data):
        addons = data.pop("addons", None)
        g = super().update(inst, data)
        self._save_addons(g, addons)
        return g


class ItemSerializer(TenantSerializer):
    variants = VariantSerializer(many=True, required=False)
    addon_groups = serializers.SerializerMethodField()
    category_name = serializers.CharField(source="category.name", read_only=True)
    effective_tax = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    in_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Item
        exclude = ["restaurant"]

    def get_addon_groups(self, obj):
        return [{"id": g.id, "name": g.name, "min_select": g.min_select, "max_select": g.max_select,
                 "addons": [{"id": a.id, "name": a.name, "price": str(a.price)} for a in g.addons.all() if a.is_available]}
                for g in obj.addon_groups.all()]

    def _save_variants(self, item, variants):
        if variants is None:
            return
        keep = []
        for v in variants:
            obj, _ = Variant.objects.update_or_create(item=item, pk=v.get("id"), defaults={"name": v["name"], "price": v["price"]})
            keep.append(obj.pk)
        item.variants.exclude(pk__in=keep).delete()

    def create(self, data):
        variants = data.pop("variants", [])
        item = super().create(data)
        self._save_variants(item, variants)
        return item

    def update(self, inst, data):
        variants = data.pop("variants", None)
        item = super().update(inst, data)
        self._save_variants(item, variants)
        return item
