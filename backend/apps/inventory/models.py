from decimal import Decimal

from django.db import models

from apps.tenants.models import TenantModel


class Supplier(TenantModel):
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Ingredient(TenantModel):
    UNITS = [("kg", "kg"), ("g", "g"), ("l", "litre"), ("ml", "ml"), ("pc", "piece"), ("pack", "pack")]

    name = models.CharField(max_length=120)
    unit = models.CharField(max_length=5, choices=UNITS, default="kg")
    stock = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    reorder_level = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    cost_per_unit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.unit})"

    @property
    def is_low(self):
        return self.stock <= self.reorder_level

    @property
    def stock_value(self):
        return (self.stock * self.cost_per_unit).quantize(Decimal("0.01"))


class RecipeLine(models.Model):
    """How much of an ingredient one unit of a menu item consumes."""

    item = models.ForeignKey("menu.Item", on_delete=models.CASCADE, related_name="recipe")
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE, related_name="used_in")
    quantity = models.DecimalField(max_digits=10, decimal_places=3)

    class Meta:
        unique_together = ("item", "ingredient")


class StockMovement(TenantModel):
    KINDS = [("purchase", "Purchase"), ("consumption", "Sale consumption"), ("wastage", "Wastage"),
             ("adjustment", "Adjustment"), ("transfer", "Transfer")]

    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE, related_name="movements")
    kind = models.CharField(max_length=12, choices=KINDS)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, help_text="Positive adds, negative removes")
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    reference = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def record(cls, ingredient, kind, quantity, reference="", unit_cost=None):
        quantity = Decimal(str(quantity))
        ingredient.stock += quantity
        if kind == "purchase" and unit_cost:
            ingredient.cost_per_unit = Decimal(str(unit_cost))
        ingredient.save(update_fields=["stock", "cost_per_unit", "updated_at"])
        return cls.objects.create(restaurant=ingredient.restaurant, ingredient=ingredient, kind=kind,
                                  quantity=quantity, unit_cost=unit_cost or ingredient.cost_per_unit, reference=reference)


class PurchaseOrder(TenantModel):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_orders")
    status = models.CharField(max_length=10, default="draft")  # draft / ordered / received / cancelled
    expected_on = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=200, blank=True)

    @property
    def total(self):
        return sum((l.quantity * l.unit_cost for l in self.lines.all()), Decimal("0"))

    def receive(self):
        for line in self.lines.select_related("ingredient"):
            StockMovement.record(line.ingredient, "purchase", line.quantity, f"PO-{self.pk}", line.unit_cost)
        self.status = "received"
        self.save()


class PurchaseLine(models.Model):
    po = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)
