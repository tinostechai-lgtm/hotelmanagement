from decimal import Decimal

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.menu.models import Item
from apps.operations.models import Order, Table
from apps.tenants.models import Restaurant


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed", demo=True, stdout=open("/dev/null", "w"))

    def setUp(self):
        cache.clear()
        self.c = APIClient()
        res = self.c.post("/api/auth/login", {"phone": "9999999999", "password": "Demo@1234"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.c.credentials(HTTP_AUTHORIZATION="Bearer " + res.json()["access"])
        self.r = Restaurant.objects.get(slug="spice-garden")
        # These flows check GST maths, so this restaurant charges GST (the default for new ones is off).
        Restaurant.objects.filter(pk=self.r.pk).update(gst_enabled=True)
        self.r.refresh_from_db()

    def item(self, name):
        return Item.objects.get(restaurant=self.r, name=name)


class POSFlowTests(Base):
    def test_bootstrap(self):
        res = self.c.get("/api/bootstrap")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["menu"])
        self.assertIn("pos", res.json()["features"])

    def test_dine_in_full_cycle(self):
        t = Table.objects.filter(restaurant=self.r).first()
        res = self.c.post("/api/orders", {"table": t.id, "guests": 2, "items": [
            {"item_id": self.item("Paneer Tikka").id, "quantity": 2},
            {"item_id": self.item("Cold Coffee").id, "quantity": 1}], "send_kot": True}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        o = res.json()
        self.assertEqual(len(o["kots"]), 2)  # kitchen + bar routing
        # 2*260 + 140 = 660 ; 5% service = 33 ; 5% GST on 660 = 33 ; total 726
        self.assertEqual(Decimal(o["subtotal"]), Decimal("660"))
        self.assertEqual(Decimal(o["total"]), Decimal("726"))
        t.refresh_from_db()
        self.assertEqual(t.status, "occupied")
        # kitchen marks ready
        for k in o["kots"]:
            self.assertEqual(self.c.post(f"/api/kots/{k['id']}/status", {"status": "ready"}, format="json").status_code, 200)
        res = self.c.post(f"/api/orders/{o['id']}/bill", {}, format="json")
        self.assertEqual(res.json()["status"], "ready")
        res = self.c.post(f"/api/orders/{o['id']}/pay", {"payments": [{"method": "cash", "amount": 500}, {"method": "upi", "amount": 226}]}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["status"], "completed")
        self.assertTrue(res.json()["is_paid"])
        t.refresh_from_db()
        self.assertEqual(t.status, "cleaning")
        # inventory deducted (2 x 0.18 kg paneer)
        from apps.inventory.models import Ingredient
        self.assertEqual(Ingredient.objects.get(restaurant=self.r, name="Paneer").stock, Decimal("9.640"))

    def test_split_equal_and_items(self):
        res = self.c.post("/api/orders", {"order_type": "dine_in", "table": Table.objects.filter(restaurant=self.r)[1].id, "items": [
            {"item_id": self.item("Butter Naan").id, "quantity": 4, "seat": 1},
            {"item_id": self.item("Dal Makhani").id, "quantity": 1, "seat": 2}]}, format="json")
        oid = res.json()["id"]
        res = self.c.post(f"/api/orders/{oid}/split", {"mode": "equal", "parts": 3}, format="json")
        bills = [b for b in res.json()["bills"] if b["status"] != "void"]
        self.assertEqual(len(bills), 3)
        self.assertEqual(sum(Decimal(b["total"]) for b in bills), Decimal(res.json()["total"]))
        res = self.c.post(f"/api/orders/{oid}/split", {"mode": "seat"}, format="json")
        bills = [b for b in res.json()["bills"] if b["status"] != "void"]
        self.assertEqual(len(bills), 2)
        for b in bills:
            self.c.post(f"/api/orders/{oid}/pay", {"method": "card", "amount": b["total"], "bill": b["id"]}, format="json")
        self.assertEqual(Order.objects.get(pk=oid).status, "completed")

    def test_coupon_and_void_permission(self):
        res = self.c.post("/api/orders", {"order_type": "takeaway", "items": [{"item_id": self.item("Butter Chicken").id, "quantity": 1}]}, format="json")
        oid = res.json()["id"]
        res = self.c.post(f"/api/orders/{oid}/discount", {"coupon": "WELCOME20"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(Decimal(res.json()["discount"]), Decimal("76.00"))
        # captain cannot cancel
        cap = APIClient()
        tok = cap.post("/api/auth/login", {"phone": "8888888801", "password": "Demo@1234"}, format="json").json()["access"]
        cap.credentials(HTTP_AUTHORIZATION="Bearer " + tok)
        self.assertEqual(cap.post(f"/api/orders/{oid}/status", {"status": "cancelled"}, format="json").status_code, 403)
        self.assertEqual(cap.get("/api/reports/summary").status_code, 403)

    def test_room_service_post_to_room(self):
        from apps.operations.models import Room

        room = Room.objects.get(restaurant=self.r, number="101")
        res = self.c.post("/api/orders", {"order_type": "room_service", "room": room.id, "items": [{"item_id": self.item("Masala Chai").id, "quantity": 2}]}, format="json")
        o = res.json()
        res = self.c.post(f"/api/orders/{o['id']}/pay", {"method": "room", "amount": o["total"]}, format="json")
        self.assertTrue(res.json()["is_paid"])

    def test_reports_and_insights(self):
        self.test_dine_in_full_cycle()
        res = self.c.get("/api/reports/summary").json()
        self.assertEqual(Decimal(res["sales"]), Decimal("726"))
        self.assertEqual(self.c.get("/api/reports/insights").status_code, 200)

    def test_offline_idempotency(self):
        body = {"order_type": "takeaway", "client_ref": "dev1-0001", "items": [{"item_id": self.item("Masala Chai").id, "quantity": 1}]}
        a = self.c.post("/api/orders", body, format="json").json()
        b = self.c.post("/api/orders", body, format="json").json()
        self.assertEqual(a["id"], b["id"])


class DeliveryTests(Base):
    def test_online_delivery_order_with_razorpay_demo_and_rider(self):
        pub = APIClient()
        store = pub.get("/api/public/spice-garden/store").json()
        self.assertTrue(store["store"]["delivery"])
        res = pub.post("/api/public/spice-garden/order", {
            "mode": "delivery", "name": "Anu", "phone": "9876543210", "address": "Flat 2, Marine Drive", "lat": "9.9400", "lng": "76.2700",
            "payment": "online", "items": [{"item_id": self.item("Chicken Biryani").id, "quantity": 2}]}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        data = res.json()
        # 640 + 5% gst 32 + delivery 0 (free above 599) + packing 15 = 687
        self.assertEqual(Decimal(data["order"]["total"]), Decimal("687"))
        rz = data["razorpay"]
        res = pub.post("/api/public/spice-garden/verify-payment", {"razorpay_order_id": rz["order_id"], "razorpay_payment_id": "pay_demo", "razorpay_signature": "x"}, format="json")
        self.assertTrue(res.json()["order"]["is_paid"])
        order = Order.objects.get(tracking_token=data["order"]["token"])
        self.assertEqual(order.status, "pending")
        self.c.post(f"/api/orders/{order.id}/status", {"status": "accepted"}, format="json")
        # rider flow
        rider_c = APIClient()
        tok = rider_c.post("/api/auth/login", {"phone": "8888888804", "password": "Demo@1234"}, format="json").json()["access"]
        rider_c.credentials(HTTP_AUTHORIZATION="Bearer " + tok)
        rider_c.post("/api/rider", {"action": "online"}, format="json")
        rider_c.post("/api/rider", {"action": "ping", "lat": "9.93", "lng": "76.26"}, format="json")
        task = order.delivery
        self.assertEqual(self.c.post(f"/api/delivery/tasks/{task.id}/assign", {"auto": True}, format="json").status_code, 200)
        me = rider_c.get("/api/rider").json()
        self.assertEqual(len(me["tasks"]), 1)
        rider_c.post("/api/rider", {"action": "pickup", "task": task.id}, format="json")
        bad = rider_c.post("/api/rider", {"action": "deliver", "task": task.id, "otp": "x"}, format="json")
        self.assertEqual(bad.status_code, 400)
        task.refresh_from_db()
        ok = rider_c.post("/api/rider", {"action": "deliver", "task": task.id, "otp": task.otp}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
        order.refresh_from_db()
        self.assertEqual(order.status, "delivered")
        track = pub.get(f"/api/public/track/{order.tracking_token}").json()
        self.assertEqual(track["status"], "delivered")
        res = self.c.post(f"/api/delivery/riders/{task.rider_id}/settle", {}, format="json")
        self.assertEqual(res.json()["deliveries"], 1)
        order.refresh_from_db()
        self.assertEqual(order.status, "completed")

    def test_cod_order_and_out_of_range(self):
        pub = APIClient()
        far = pub.post("/api/public/spice-garden/order", {"mode": "delivery", "name": "X", "phone": "9876543211", "address": "Far", "lat": "10.5", "lng": "76.2",
                                                          "payment": "cod", "items": [{"item_id": self.item("Masala Chai").id, "quantity": 1}]}, format="json")
        self.assertEqual(far.status_code, 400)

    def test_qr_table_order(self):
        t = Table.objects.filter(restaurant=self.r).last()
        pub = APIClient()
        store = pub.get(f"/api/public/spice-garden/store?table={t.qr_token}").json()
        self.assertEqual(store["table"]["name"], t.name)
        res = pub.post("/api/public/spice-garden/order", {"mode": "dine_in", "table_token": t.qr_token, "name": "Guest", "phone": "9000000000",
                                                          "payment": "later", "items": [{"item_id": self.item("Gulab Jamun").id, "quantity": 2}]}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(self.c.get("/api/orders/live").json()["pending_online"], 1)


class SaasTests(TestCase):
    def setUp(self):
        cache.clear()
        call_command("seed", stdout=open("/dev/null", "w"))

    def test_signup_trial_and_upgrade(self):
        c = APIClient()
        res = c.post("/api/auth/signup", {"name": "Tino Mathew", "phone": "9123456789", "password": "Secret@123", "restaurant_name": "Tino's Cafe"}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        c.credentials(HTTP_AUTHORIZATION="Bearer " + res.json()["access"])
        sub = c.get("/api/subscription").json()
        self.assertEqual(sub["status"], "trial")
        co = c.post("/api/subscription/checkout", {"plan": "growth", "cycle": "yearly"}, format="json").json()
        self.assertTrue(co["demo"])
        self.assertEqual(co["amount"], 2948820)
        v = c.post("/api/subscription/verify", {"razorpay_order_id": co["order_id"], "razorpay_payment_id": "pay_x", "razorpay_signature": "s"}, format="json")
        self.assertEqual(v.status_code, 200)
        sub = c.get("/api/subscription").json()
        self.assertEqual((sub["status"], sub["plan"]["code"], sub["cycle"]), ("active", "growth", "yearly"))
        # growth lacks aggregators/room service
        self.assertEqual(c.get("/api/rooms").status_code, 403)

    @override_settings(RAZORPAY_KEY_ID="rzp_test_x", RAZORPAY_KEY_SECRET="secret")
    def test_signature_verification(self):
        import hashlib
        import hmac

        from apps.subscriptions import razorpay_client
        sig = hmac.new(b"secret", b"order_1|pay_1", hashlib.sha256).hexdigest()
        self.assertTrue(razorpay_client.verify_payment("order_1", "pay_1", sig))
        self.assertFalse(razorpay_client.verify_payment("order_1", "pay_1", "bad"))


class HardwareTests(Base):
    def test_agent_receives_kot_jobs(self):
        from apps.hardware.models import Device

        hub = Device.objects.get(restaurant=self.r, name="Counter printer")
        self.c.post("/api/orders", {"order_type": "takeaway", "send_kot": True, "items": [{"item_id": self.item("Paneer Tikka").id, "quantity": 1}]}, format="json")
        agent = APIClient()
        self.assertEqual(agent.get("/api/hardware/agent").status_code, 401)
        res = agent.get("/api/hardware/agent", HTTP_X_DEVICE_KEY=hub.agent_key).json()
        self.assertEqual(len(res["jobs"]), 1)
        self.assertIn("Paneer Tikka", res["jobs"][0]["text"])
        agent.post("/api/hardware/agent", {"results": [{"id": res["jobs"][0]["id"], "ok": True}]}, format="json", HTTP_X_DEVICE_KEY=hub.agent_key)
        self.assertEqual(agent.get("/api/hardware/agent", HTTP_X_DEVICE_KEY=hub.agent_key).json()["jobs"], [])

    def test_test_print(self):
        from apps.hardware.models import Device

        d = Device.objects.get(restaurant=self.r, name="Bar printer")
        res = self.c.post(f"/api/devices/{d.id}/test", format="json")
        self.assertIn("Printer test successful", res.json()["preview"])


class HardeningTests(Base):
    def test_login_is_rate_limited(self):
        cache.clear()
        c = APIClient()
        codes = [c.post("/api/auth/login", {"phone": "9999999999", "password": "wrong"}, format="json").status_code for _ in range(12)]
        self.assertIn(429, codes)

    def test_cannot_attach_other_restaurants_station(self):
        from apps.accounts.api import create_account
        from apps.menu.models import KitchenStation

        _, other = create_account({"name": "X Y", "phone": "9111111111", "password": "Passw0rd!", "restaurant_name": "Other"})
        foreign = KitchenStation.objects.get(restaurant=other)
        res = self.c.post("/api/devices", {"name": "P", "kind": "kot_printer", "connection": "network", "stations": [foreign.id]}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_unpaid_online_order_hidden_then_expired(self):
        from datetime import timedelta

        from django.utils import timezone

        pub = APIClient()
        res = pub.post("/api/public/spice-garden/order", {"mode": "takeaway", "name": "A", "phone": "9876500099", "payment": "online",
                                                          "items": [{"item_id": self.item("Masala Chai").id, "quantity": 1}]}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(self.c.get("/api/orders/live").json()["pending_online"], 0)
        Order.objects.filter(pk=Order.objects.latest("id").pk).update(created_at=timezone.now() - timedelta(hours=1))
        self.c.get("/api/orders/live")
        self.assertEqual(Order.objects.latest("id").status, "cancelled")

    def test_open_redirect_blocked(self):
        cache.clear()
        res = self.client.post("/login/?next=https://evil.example", {"phone": "9999999999", "password": "Demo@1234"})
        self.assertEqual(res["Location"], "/app/")
