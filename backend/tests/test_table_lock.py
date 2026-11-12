"""One attendant per table: B can't order on a table A is serving; managers can take over."""
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Role, User
from apps.operations.models import Order, OrderItem, Table

from .test_flows import Base


class TableLockTests(Base):
    def captain(self, phone, name):
        u = User.objects.create_user(username=phone, phone=phone, first_name=name, password="Pass@1234")
        Membership.objects.create(user=u, restaurant=self.r, role=Role.objects.get(restaurant=self.r, name="Captain"))
        c = APIClient()
        tok = c.post("/api/auth/login", {"phone": phone, "password": "Pass@1234"}, format="json").json()["access"]
        c.credentials(HTTP_AUTHORIZATION="Bearer " + tok)
        return c

    def setUp(self):
        super().setUp()
        self.a = self.captain("7000000001", "Anil")
        self.b = self.captain("7000000002", "Biju")
        self.t = Table.objects.filter(restaurant=self.r).first()
        self.coffee = self.item("Cold Coffee")

    def order(self, client, ref):
        return client.post("/api/orders", {"table": self.t.id, "client_ref": ref,
                                           "items": [{"item_id": self.coffee.id, "quantity": 1}]}, format="json")

    def test_b_cannot_open_a_table_a_is_using(self):
        self.assertEqual(self.a.post(f"/api/tables/{self.t.id}/lock", {}, format="json").status_code, 200)
        res = self.b.post(f"/api/tables/{self.t.id}/lock", {}, format="json")
        self.assertEqual(res.status_code, 409)
        self.assertIn("Anil", res.json()["detail"])
        # B can't place an order on it either, even without opening it first
        res = self.order(self.b, "b-1")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(Order.objects.filter(table=self.t).count(), 0)
        # tables list shows who has it
        data = self.b.get("/api/tables").json()
        rows = data["results"] if isinstance(data, dict) else data
        t = next(x for x in rows if x["id"] == self.t.id)
        self.assertEqual(t["in_use_by"]["name"], "Anil")

    def test_b_cannot_add_to_a_running_order_of_a(self):
        o = self.order(self.a, "a-1").json()
        self.a.post(f"/api/tables/{self.t.id}/unlock", {}, format="json")  # A closed the screen
        self.assertEqual(self.order(self.b, "b-1").status_code, 409)
        res = self.b.post(f"/api/orders/{o['id']}/items", {"items": [{"item_id": self.coffee.id}]}, format="json")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(OrderItem.objects.filter(order_id=o["id"]).count(), 1)
        # A can keep adding
        self.assertEqual(self.a.post(f"/api/orders/{o['id']}/items", {"items": [{"item_id": self.coffee.id}]}, format="json").status_code, 200)

    def test_expired_lock_frees_the_table(self):
        self.a.post(f"/api/tables/{self.t.id}/lock", {}, format="json")
        Table.objects.filter(pk=self.t.pk).update(locked_at=timezone.now() - timedelta(minutes=5))
        self.assertEqual(self.b.post(f"/api/tables/{self.t.id}/lock", {}, format="json").status_code, 200)

    def test_manager_can_take_over(self):
        o = self.order(self.a, "a-1").json()
        res = self.c.post(f"/api/tables/{self.t.id}/lock", {}, format="json")  # self.c = owner
        self.assertEqual(res.status_code, 409)
        self.assertTrue(res.json()["can_take_over"])
        self.assertEqual(self.c.post(f"/api/tables/{self.t.id}/lock", {"take_over": True}, format="json").status_code, 200)
        self.assertEqual(Order.objects.get(pk=o["id"]).taken_by.username, "9999999999")
        # captain B still can't take it over
        self.assertEqual(self.b.post(f"/api/tables/{self.t.id}/lock", {"take_over": True}, format="json").status_code, 409)

    def test_after_bill_settled_table_is_free_again(self):
        o = self.order(self.a, "a-1").json()
        self.c.post(f"/api/orders/{o['id']}/pay", {"method": "cash"}, format="json")
        self.a.post(f"/api/tables/{self.t.id}/unlock", {}, format="json")
        self.assertEqual(self.order(self.b, "b-new").status_code, 201)
