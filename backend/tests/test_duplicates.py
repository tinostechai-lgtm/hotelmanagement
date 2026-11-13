"""A table must never get a second open order or the same items twice (retries, double taps, offline replays)."""
from .test_flows import Base
from apps.operations.models import KOT, Order, OrderItem, Table


class TableDuplicateTests(Base):
    def setUp(self):
        super().setUp()
        self.t = Table.objects.filter(restaurant=self.r).first()
        self.coffee = self.item("Cold Coffee")

    def post_order(self, ref, qty=1, confirm=False):
        return self.c.post("/api/orders", {"table": self.t.id, "client_ref": ref, "send_kot": True, "confirm_duplicate": confirm,
                                           "items": [{"item_id": self.coffee.id, "quantity": qty}]}, format="json")

    def open_orders(self):
        return Order.objects.filter(table=self.t, status__in=Order.OPEN_STATUSES)

    def test_two_devices_same_table_share_one_order(self):
        a = self.post_order("dev-a-1").json()
        dup = self.post_order("dev-b-1")  # second crew enters the very same items -> stopped
        self.assertEqual(dup.status_code, 409)
        self.assertEqual(dup.json()["code"], "duplicate_items")
        self.assertEqual(OrderItem.objects.filter(order_id=a["id"]).count(), 1)
        b = self.post_order("dev-b-1", confirm=True).json()  # guest really ordered again
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(self.open_orders().count(), 1)
        self.assertEqual(OrderItem.objects.filter(order_id=a["id"]).count(), 2)

    def test_resent_create_does_not_add_items_twice(self):
        first = self.post_order("same-ref").json()
        again = self.post_order("same-ref").json()  # e.g. app timed out, then retried / replayed offline
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(OrderItem.objects.filter(order_id=first["id"]).count(), 1)
        self.assertEqual(KOT.objects.filter(order_id=first["id"]).count(), 1)

    def test_resent_merge_into_running_order_is_ignored(self):
        o = self.post_order("first").json()
        self.post_order("second", qty=2)      # another batch merged into the table's running order
        self.post_order("second", qty=2)      # same batch re-sent
        self.assertEqual(OrderItem.objects.filter(order_id=o["id"]).count(), 2)
        self.assertEqual(self.open_orders().count(), 1)

    def test_add_items_with_same_client_ref_is_idempotent(self):
        o = self.post_order("start").json()
        body = {"items": [{"item_id": self.coffee.id, "quantity": 2}], "send_kot": True, "client_ref": "batch-42"}
        for _ in range(3):  # double tap + retry
            res = self.c.post(f"/api/orders/{o['id']}/items", body, format="json")
            self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(OrderItem.objects.filter(order_id=o["id"]).count(), 2)
        self.assertEqual(KOT.objects.filter(order_id=o["id"]).count(), 2)
        # the same items again from another request -> asks first; confirmed -> added
        self.assertEqual(self.c.post(f"/api/orders/{o['id']}/items", {**body, "client_ref": "batch-43"}, format="json").status_code, 409)
        self.c.post(f"/api/orders/{o['id']}/items", {**body, "client_ref": "batch-43", "confirm_duplicate": True}, format="json")
        self.assertEqual(OrderItem.objects.filter(order_id=o["id"]).count(), 3)

    def test_add_items_without_ref_still_works(self):
        o = self.post_order("x").json()
        tikka = self.item("Paneer Tikka")
        self.assertEqual(self.c.post(f"/api/orders/{o['id']}/items", {"items": [{"item_id": tikka.id}]}, format="json").status_code, 200)
        self.assertEqual(self.c.post(f"/api/orders/{o['id']}/items", {"items": [{"item_id": tikka.id, "quantity": 2}]}, format="json").status_code, 200)
        self.assertEqual(OrderItem.objects.filter(order_id=o["id"]).count(), 3)

    def test_same_items_twice_without_ref_are_stopped(self):
        o = self.post_order("x").json()
        tikka = self.item("Paneer Tikka")
        self.c.post(f"/api/orders/{o['id']}/items", {"items": [{"item_id": tikka.id}]}, format="json")
        res = self.c.post(f"/api/orders/{o['id']}/items", {"items": [{"item_id": tikka.id}]}, format="json")
        self.assertEqual(res.status_code, 409)
        self.assertIn("already added", res.json()["detail"])
        self.assertEqual(OrderItem.objects.filter(order_id=o["id"]).count(), 2)

    def test_same_items_allowed_again_after_window(self):
        from datetime import timedelta

        from django.utils import timezone

        o = self.post_order("x").json()
        OrderItem.objects.filter(order_id=o["id"]).update(created_at=timezone.now() - timedelta(minutes=10))
        self.assertEqual(self.post_order("later").status_code, 201)  # 10 min later: a real repeat order
