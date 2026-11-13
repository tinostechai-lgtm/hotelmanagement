"""Menu delete: one item, several at once, whole categories - past orders keep their item names."""
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Role, User
from apps.menu.models import Category, Item
from apps.operations.models import OrderItem, Table
from apps.tenants.models import Restaurant

from .test_flows import Base


class MenuDeleteTests(Base):
    def test_single_and_bulk_item_delete(self):
        a, b, c = Item.objects.filter(restaurant=self.r)[:3]
        self.assertEqual(self.c.delete(f"/api/items/{a.id}").status_code, 204)
        res = self.c.post("/api/items/bulk-delete", {"ids": [b.id, c.id]}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["deleted"], 2)
        self.assertFalse(Item.objects.filter(pk__in=[a.id, b.id, c.id]).exists())

    def test_bulk_delete_only_touches_own_restaurant(self):
        other = Restaurant.objects.exclude(pk=self.r.pk).first()
        if other is None:
            other = Restaurant.objects.create(name="Other place", slug="other-place")
        cat = Category.objects.create(restaurant=other, name="Theirs")
        theirs = Item.objects.create(restaurant=other, category=cat, name="Their item", price=10)
        mine = Item.objects.filter(restaurant=self.r).first()
        res = self.c.post("/api/items/bulk-delete", {"ids": [theirs.id, mine.id]}, format="json")
        self.assertEqual(res.json()["deleted"], 1)
        self.assertTrue(Item.objects.filter(pk=theirs.id).exists())

    def test_past_orders_keep_item_names(self):
        it = self.item("Cold Coffee")
        t = Table.objects.filter(restaurant=self.r).first()
        o = self.c.post("/api/orders", {"table": t.id, "items": [{"item_id": it.id}]}, format="json").json()
        self.c.post("/api/items/bulk-delete", {"ids": [it.id]}, format="json")
        line = OrderItem.objects.get(order_id=o["id"])
        self.assertEqual(line.name, "Cold Coffee")
        self.assertIsNone(line.item_id)

    def test_bulk_delete_categories_removes_their_items(self):
        cat = Category.objects.filter(restaurant=self.r).first()
        n_items = cat.items.count()
        self.assertGreater(n_items, 0)
        res = self.c.post("/api/categories/bulk-delete", {"ids": [cat.id]}, format="json")
        self.assertEqual(res.json()["deleted"], 1)
        self.assertFalse(Item.objects.filter(category_id=cat.id).exists())

    def test_staff_without_menu_permission_cannot_delete(self):
        u = User.objects.create_user(username="7100000001", phone="7100000001", first_name="Cap", password="Pass@1234")
        Membership.objects.create(user=u, restaurant=self.r, role=Role.objects.get(restaurant=self.r, name="Captain"))
        cap = APIClient()
        cap.credentials(HTTP_AUTHORIZATION="Bearer " + cap.post("/api/auth/login", {"phone": "7100000001", "password": "Pass@1234"}, format="json").json()["access"])
        it = Item.objects.filter(restaurant=self.r).first()
        self.assertEqual(cap.post("/api/items/bulk-delete", {"ids": [it.id]}, format="json").status_code, 403)
        self.assertTrue(Item.objects.filter(pk=it.id).exists())

    def test_bad_payload(self):
        self.assertEqual(self.c.post("/api/items/bulk-delete", {"ids": "all"}, format="json").status_code, 400)
