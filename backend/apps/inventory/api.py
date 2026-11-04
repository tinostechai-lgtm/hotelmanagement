from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.tenants.api_base import TenantSerializer, TenantViewSet

from .models import Ingredient, PurchaseLine, PurchaseOrder, RecipeLine, StockMovement, Supplier


class SupplierSerializer(TenantSerializer):
    class Meta:
        model = Supplier
        exclude = ["restaurant"]


class IngredientSerializer(TenantSerializer):
    is_low = serializers.BooleanField(read_only=True)
    stock_value = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Ingredient
        exclude = ["restaurant"]
        read_only_fields = ["stock"]


class MovementSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(source="ingredient.name", read_only=True)

    class Meta:
        model = StockMovement
        exclude = ["restaurant"]


class RecipeSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(source="ingredient.name", read_only=True)
    unit = serializers.CharField(source="ingredient.unit", read_only=True)

    class Meta:
        model = RecipeLine
        fields = "__all__"


class POLineSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(source="ingredient.name", read_only=True)

    class Meta:
        model = PurchaseLine
        exclude = ["po"]


class POSerializer(TenantSerializer):
    lines = POLineSerializer(many=True)
    total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)

    class Meta:
        model = PurchaseOrder
        exclude = ["restaurant"]
        read_only_fields = ["status"]

    def validate_lines(self, lines):
        if not lines:
            raise serializers.ValidationError("Add at least one line")
        return lines

    def create(self, data):
        lines = data.pop("lines")
        po = PurchaseOrder.objects.create(**data)
        for line in lines:
            PurchaseLine.objects.create(po=po, **line)
        return po

    def update(self, po, data):
        if po.status == "received":
            raise serializers.ValidationError("A received purchase order can't be edited")
        lines = data.pop("lines", None)
        po = super().update(po, data)
        if lines is not None:
            po.lines.all().delete()
            for line in lines:
                PurchaseLine.objects.create(po=po, **line)
        return po


class SupplierViewSet(TenantViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    perm = read_perm = "inventory"
    feature = "inventory"


class IngredientViewSet(TenantViewSet):
    queryset = Ingredient.objects.select_related("supplier")
    serializer_class = IngredientSerializer
    perm = read_perm = "inventory"
    feature = "inventory"

    @action(detail=True, methods=["post"])
    def adjust(self, request, pk=None):
        """{kind: purchase|wastage|adjustment, quantity, unit_cost?, reference?}"""
        ing = self.get_object()
        kind = request.data.get("kind", "adjustment")
        qty = request.data.get("quantity", 0)
        if kind == "wastage":
            qty = -abs(float(qty))
        StockMovement.record(ing, kind, qty, request.data.get("reference", ""), request.data.get("unit_cost"))
        ing.refresh_from_db()
        return Response(IngredientSerializer(ing).data)

    @action(detail=False)
    def low(self, request):
        return Response(IngredientSerializer([i for i in self.get_queryset() if i.is_low], many=True).data)


class MovementViewSet(TenantViewSet):
    queryset = StockMovement.objects.select_related("ingredient")
    serializer_class = MovementSerializer
    perm = read_perm = "inventory"
    http_method_names = ["get", "head", "options"]


class RecipeViewSet(TenantViewSet):
    queryset = RecipeLine.objects.select_related("ingredient")
    serializer_class = RecipeSerializer
    perm = read_perm = "inventory"

    def get_queryset(self):
        qs = RecipeLine.objects.filter(item__restaurant=self.request.restaurant).select_related("ingredient")
        if self.request.query_params.get("item"):
            qs = qs.filter(item_id=self.request.query_params["item"])
        return qs

    def perform_create(self, serializer):
        item, ing = serializer.validated_data["item"], serializer.validated_data["ingredient"]
        if item.restaurant_id != self.request.restaurant.id or ing.restaurant_id != self.request.restaurant.id:
            raise serializers.ValidationError("Not found")
        serializer.save()


class PurchaseOrderViewSet(TenantViewSet):
    queryset = PurchaseOrder.objects.select_related("supplier").prefetch_related("lines__ingredient")
    serializer_class = POSerializer
    perm = read_perm = "inventory"
    feature = "inventory"

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        po = self.get_object()
        if po.status == "received":
            return Response({"detail": "Already received"}, status=400)
        po.receive()
        return Response(POSerializer(po).data)
