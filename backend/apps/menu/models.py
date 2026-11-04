from decimal import Decimal

from django.db import models

from apps.tenants.models import TenantModel


class HSNCode(TenantModel):
    code = models.CharField(max_length=10)
    description = models.CharField(max_length=120, blank=True)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("5"))
    cess_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta:
        unique_together = ("restaurant", "code")

    def __str__(self):
        return f"{self.code} ({self.gst_percent}%)"


class KitchenStation(TenantModel):
    """Where KOTs are routed: Main kitchen, Bar, Tandoor, Desserts …"""

    name = models.CharField(max_length=60)

    def __str__(self):
        return self.name


class Category(TenantModel):
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=200, blank=True)
    image_url = models.URLField(blank=True)
    sort = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    station = models.ForeignKey(KitchenStation, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["sort", "name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Item(TenantModel):
    class Diet(models.TextChoices):
        VEG = "veg", "Veg"
        NON_VEG = "non_veg", "Non-veg"
        EGG = "egg", "Egg"
        VEGAN = "vegan", "Vegan"

    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="items")
    name = models.CharField(max_length=120)
    short_code = models.CharField(max_length=12, blank=True, help_text="Type-to-bill shortcut, e.g. PBM")
    barcode = models.CharField(max_length=40, blank=True)
    description = models.TextField(blank=True)
    image_url = models.URLField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    delivery_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    hsn = models.ForeignKey(HSNCode, null=True, blank=True, on_delete=models.SET_NULL)
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("5"))
    diet = models.CharField(max_length=8, choices=Diet.choices, default=Diet.VEG)
    station = models.ForeignKey(KitchenStation, null=True, blank=True, on_delete=models.SET_NULL)
    prep_minutes = models.PositiveIntegerField(default=15)
    is_available = models.BooleanField(default=True, help_text="Real-time availability toggle (86 an item)")
    track_stock = models.BooleanField(default=False)
    stock_qty = models.IntegerField(default=0)
    available_dine_in = models.BooleanField(default=True)
    available_online = models.BooleanField(default=True)
    is_bestseller = models.BooleanField(default=False)
    is_weighted = models.BooleanField(default=False, help_text="Sold by weight (uses weighing scale)")
    spice_level = models.PositiveSmallIntegerField(default=0)
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort", "name"]

    def __str__(self):
        return self.name

    @property
    def effective_tax(self):
        return self.hsn.gst_percent if self.hsn_id else self.tax_percent

    @property
    def in_stock(self):
        return self.is_available and (not self.track_stock or self.stock_qty > 0)

    def kitchen_station(self):
        return self.station or self.category.station


class Variant(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="variants")
    name = models.CharField(max_length=60)  # Half / Full / Large
    price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.item} — {self.name}"


class AddonGroup(TenantModel):
    name = models.CharField(max_length=80)
    min_select = models.PositiveSmallIntegerField(default=0)
    max_select = models.PositiveSmallIntegerField(default=5)
    items = models.ManyToManyField(Item, related_name="addon_groups", blank=True)

    def __str__(self):
        return self.name


class Addon(models.Model):
    group = models.ForeignKey(AddonGroup, on_delete=models.CASCADE, related_name="addons")
    name = models.CharField(max_length=80)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_available = models.BooleanField(default=True)

    def __str__(self):
        return self.name
