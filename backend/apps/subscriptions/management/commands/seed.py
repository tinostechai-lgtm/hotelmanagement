from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

PLANS = [
    dict(code="starter", name="Starter", sort=1, tagline="Everything a single counter needs to bill fast",
         price_monthly=Decimal("999"), price_yearly=Decimal("9990"), max_users=3, max_devices=2,
         features=["pos", "kot", "tables", "menu", "offline", "reports", "qr_menu"]),
    dict(code="growth", name="Growth", sort=2, is_popular=True, tagline="Online orders, home delivery & loyalty",
         price_monthly=Decimal("2499"), price_yearly=Decimal("24990"), max_users=10, max_devices=0,
         features=["pos", "kot", "tables", "menu", "offline", "reports", "qr_menu", "qr_ordering", "split_bill", "kds",
                   "online_ordering", "delivery", "crm", "inventory"]),
    dict(code="pro", name="Pro", sort=3, tagline="Hotels, aggregators, riders & AI insights",
         price_monthly=Decimal("4999"), price_yearly=Decimal("49990"), max_users=0, max_devices=0, max_outlets=3,
         features=["pos", "kot", "tables", "menu", "offline", "reports", "qr_menu", "qr_ordering", "split_bill", "kds",
                   "online_ordering", "delivery", "crm", "inventory", "room_service", "aggregators", "rider_app",
                   "analytics_ai", "multi_outlet", "api_access"]),
    dict(code="enterprise", name="Enterprise", sort=4, tagline="Chains & hotel groups — custom SLAs",
         price_monthly=Decimal("0"), price_yearly=Decimal("0"), max_users=0, max_devices=0, max_outlets=0, is_public=True,
         features=["pos", "kot", "tables", "menu", "offline", "reports", "qr_menu", "qr_ordering", "split_bill", "kds",
                   "online_ordering", "delivery", "crm", "inventory", "room_service", "aggregators", "rider_app",
                   "analytics_ai", "multi_outlet", "api_access"]),
]

MENU = {
    "Starters": [("Paneer Tikka", 260, "veg", True), ("Chicken 65", 290, "non_veg", True), ("Crispy Corn", 210, "veg", False),
                 ("Fish Amritsari", 340, "non_veg", False), ("Hara Bhara Kebab", 220, "veg", False)],
    "Main Course": [("Butter Chicken", 380, "non_veg", True), ("Paneer Butter Masala", 320, "veg", True),
                    ("Dal Makhani", 260, "veg", False), ("Kerala Fish Curry", 360, "non_veg", False),
                    ("Mutton Rogan Josh", 440, "non_veg", False)],
    "Breads & Rice": [("Butter Naan", 60, "veg", False), ("Garlic Naan", 75, "veg", True), ("Malabar Parotta", 45, "veg", False),
                      ("Veg Biryani", 260, "veg", False), ("Chicken Biryani", 320, "non_veg", True)],
    "Beverages": [("Fresh Lime Soda", 90, "veg", False), ("Masala Chai", 50, "veg", False), ("Cold Coffee", 140, "veg", True),
                  ("Mango Lassi", 120, "veg", False)],
    "Desserts": [("Gulab Jamun", 90, "veg", False), ("Sizzling Brownie", 210, "veg", True), ("Kulfi Falooda", 160, "veg", False)],
}


class Command(BaseCommand):
    help = "Create SaaS plans and (optionally) a fully populated demo restaurant."

    def add_arguments(self, parser):
        parser.add_argument("--demo", action="store_true", help="Also create the demo restaurant & login")

    @transaction.atomic
    def handle(self, *args, **opts):
        from apps.subscriptions.models import Plan

        for p in PLANS:
            Plan.objects.update_or_create(code=p["code"], defaults=p)
        self.stdout.write(self.style.SUCCESS(f"{len(PLANS)} plans ready"))
        if opts["demo"]:
            self.demo()

    def demo(self):
        from apps.accounts.models import Membership, Role, User
        from apps.crm.models import Coupon, Customer
        from apps.delivery.models import DeliveryZone, Rider
        from apps.hardware.models import Device
        from apps.inventory.models import Ingredient, RecipeLine, Supplier
        from apps.menu.models import AddonGroup, Addon, Category, HSNCode, Item, KitchenStation, Variant
        from apps.operations.models import Area, Room, Table
        from apps.subscriptions.models import Subscription
        from apps.tenants.models import Restaurant

        user, created = User.objects.get_or_create(username="9999999999", defaults={"first_name": "Demo", "last_name": "Owner", "phone": "9999999999", "pin": "1234"})
        if created:
            user.set_password("Demo@1234")
            user.save()
        r, created = Restaurant.objects.get_or_create(slug="spice-garden", defaults=dict(
            name="Spice Garden", owner=user, phone="9999999999", email="hello@spicegarden.example", business_type="hotel",
            address="12 MG Road, Kochi", city="Kochi", state="Kerala", pincode="682016", latitude=Decimal("9.9312"),
            longitude=Decimal("76.2673"), gstin="32ABCDE1234F1Z5", fssai="11322999000123", service_charge_percent=Decimal("5"),
            delivery_fee=Decimal("30"), free_delivery_above=Decimal("599"), packaging_charge=Decimal("15")))
        Role.ensure_defaults(r)
        Membership.objects.get_or_create(user=user, restaurant=r, defaults={"role": Role.objects.get(restaurant=r, name="Owner")})
        if not r.subscriptions.exists():
            Subscription.start_trial(r, "pro", days=3650)
        if not created:
            self.stdout.write("Demo restaurant already exists")
            return
        staff = [("8888888801", "Arun", "Captain"), ("8888888802", "Meera", "Cashier"), ("8888888803", "Chef Ravi", "Kitchen"),
                 ("8888888804", "Vishnu", "Delivery Rider")]
        for phone, name, role in staff:
            u, _ = User.objects.get_or_create(username=phone, defaults={"first_name": name, "phone": phone, "pin": phone[-4:]})
            u.set_password("Demo@1234")
            u.save()
            Membership.objects.get_or_create(user=u, restaurant=r, defaults={"role": Role.objects.get(restaurant=r, name=role)})
            if role == "Delivery Rider":
                Rider.objects.create(restaurant=r, user=u, name=name, phone=phone, vehicle="Scooter", vehicle_number="KL-07-AB-1234")
        kitchen = KitchenStation.objects.create(restaurant=r, name="Main Kitchen")
        bar = KitchenStation.objects.create(restaurant=r, name="Beverage Bar")
        hsn_food = HSNCode.objects.create(restaurant=r, code="996331", description="Restaurant services", gst_percent=Decimal("5"))
        for sort, (cat, items) in enumerate(MENU.items()):
            c = Category.objects.create(restaurant=r, name=cat, sort=sort, station=bar if cat == "Beverages" else kitchen)
            for i, (name, price, diet, best) in enumerate(items):
                code = "".join(w[0] for w in name.split()).upper()
                it = Item.objects.create(restaurant=r, category=c, name=name, price=Decimal(price), diet=diet, is_bestseller=best,
                                         short_code=code, hsn=hsn_food, sort=i, description=f"House special {name.lower()}.")
                if cat in ("Main Course",) and "Dal" not in name:
                    Variant.objects.create(item=it, name="Half", price=Decimal(price) * Decimal("0.6"))
                    Variant.objects.create(item=it, name="Full", price=Decimal(price))
        extras = AddonGroup.objects.create(restaurant=r, name="Extras", max_select=3)
        for n, p in [("Extra cheese", 40), ("Extra gravy", 50), ("Less spicy", 0)]:
            Addon.objects.create(group=extras, name=n, price=Decimal(p))
        extras.items.set(Item.objects.filter(restaurant=r, category__name__in=["Starters", "Main Course"]))
        for a_i, (area, n) in enumerate([("Indoor", 8), ("Patio", 4), ("Rooftop", 4)]):
            a = Area.objects.create(restaurant=r, name=area, sort=a_i)
            for t in range(1, n + 1):
                Table.objects.create(restaurant=r, area=a, name=f"{area[0]}{t}", seats=[2, 4, 4, 6][t % 4], pos_x=t, pos_y=a_i)
        for n in ["101", "102", "103", "201", "202", "203"]:
            Room.objects.create(restaurant=r, number=n, floor=n[0], room_type="Deluxe" if n.endswith("1") else "Standard",
                                is_occupied=n in ("101", "202"), guest_name={"101": "Mr. Mathew", "202": "Ms. Anjali"}.get(n, ""))
        DeliveryZone.objects.create(restaurant=r, name="Nearby", max_km=3, fee=Decimal("20"), eta_minutes=30)
        DeliveryZone.objects.create(restaurant=r, name="City", max_km=8, fee=Decimal("45"), min_order=Decimal("199"), eta_minutes=45)
        Coupon.objects.create(restaurant=r, code="WELCOME20", description="20% off up to ₹100", value=20, max_discount=100, min_order=299)
        Coupon.objects.create(restaurant=r, code="FLAT50", description="₹50 off above ₹499", is_percent=False, value=50, min_order=499)
        for phone, name in [("9876500001", "Rahul Nair"), ("9876500002", "Priya Menon"), ("9876500003", "Joseph K")]:
            Customer.objects.create(restaurant=r, phone=phone, name=name)
        sup = Supplier.objects.create(restaurant=r, name="Fresh Farms Kochi", phone="9847000000")
        ings = {n: Ingredient.objects.create(restaurant=r, name=n, unit=u, stock=Decimal(s), reorder_level=Decimal(rl),
                                             cost_per_unit=Decimal(c), supplier=sup)
                for n, u, s, rl, c in [("Paneer", "kg", 10, 2, 320), ("Chicken", "kg", 20, 5, 240), ("Butter", "kg", 5, 1, 520),
                                       ("Basmati Rice", "kg", 25, 5, 110), ("Milk", "l", 15, 4, 56)]}
        for item_name, ing, q in [("Paneer Tikka", "Paneer", "0.180"), ("Paneer Butter Masala", "Paneer", "0.200"),
                                  ("Butter Chicken", "Chicken", "0.250"), ("Butter Chicken", "Butter", "0.030"),
                                  ("Chicken Biryani", "Chicken", "0.200"), ("Chicken Biryani", "Basmati Rice", "0.150"),
                                  ("Chicken 65", "Chicken", "0.200"), ("Masala Chai", "Milk", "0.150")]:
            RecipeLine.objects.create(item=Item.objects.get(restaurant=r, name=item_name), ingredient=ings[ing], quantity=Decimal(q))
        bill_printer = Device.objects.create(restaurant=r, name="Counter printer", kind="receipt_printer", connection="network",
                                             address="192.168.1.50:9100", is_default=True, opens_drawer=True, vendor="Epson TM-T82")
        kot1 = Device.objects.create(restaurant=r, name="Kitchen printer", kind="kot_printer", connection="network", address="192.168.1.51:9100", vendor="TVS RP3200")
        kot1.stations.add(kitchen)
        kot2 = Device.objects.create(restaurant=r, name="Bar printer", kind="kot_printer", connection="usb", address="04b8:0202", paper_width=58)
        kot2.stations.add(bar)
        Device.objects.create(restaurant=r, name="Kitchen display", kind="kds", connection="browser")
        Device.objects.create(restaurant=r, name="Cash drawer", kind="cash_drawer", connection="usb", address="via printer RJ11")
        _ = bill_printer
        self.stdout.write(self.style.SUCCESS("Demo restaurant 'Spice Garden' created. Login 9999999999 / Demo@1234"))
