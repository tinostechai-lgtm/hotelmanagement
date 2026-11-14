"""Menu items are always available: no sold-out switch, no automatic stock count. No guests prompt."""
from django.test import Client

from apps.menu.models import Item
from apps.operations.models import Table

from .test_flows import Base


class AlwaysAvailableTests(Base):
    def test_ordering_never_marks_items_sold_out(self):
        tea = self.item("Cold Coffee")
        Item.objects.filter(pk=tea.pk).update(track_stock=True, stock_qty=1)  # old stock-count data
        tables = list(Table.objects.filter(restaurant=self.r)[:3])
        for i, t in enumerate(tables):
            res = self.c.post("/api/orders", {"table": t.id, "client_ref": f"t{i}", "items": [{"item_id": tea.id, "quantity": 2}]}, format="json")
            self.assertEqual(res.status_code, 201, res.content)
            o = res.json()
            self.c.post(f"/api/orders/{o['id']}/pay", {"method": "cash"}, format="json")
        tea.refresh_from_db()
        self.assertTrue(tea.in_stock)
        menu = self.c.get("/api/bootstrap").json()["menu"]
        self.assertTrue(all(i["available"] for c in menu for i in c["items"]))

    def test_toggle_cannot_mark_unavailable(self):
        it = Item.objects.filter(restaurant=self.r).first()
        res = self.c.post(f"/api/items/{it.id}/toggle", {"available": False}, format="json")
        self.assertTrue(res.json()["is_available"])
        it.refresh_from_db()
        self.assertTrue(it.is_available)
        self.c.patch(f"/api/items/{it.id}", {"is_available": False}, format="json")
        it.refresh_from_db()
        self.assertTrue(it.is_available)

    def test_pos_and_menu_pages_have_no_guests_or_availability_controls(self):
        web = Client()
        self.assertTrue(web.login(username="9999999999", password="Demo@1234"))
        pos = web.get("/app/pos/").content.decode()
        self.assertNotIn("Number of guests", pos)
        self.assertNotIn("Change guests", pos)
        self.assertNotIn("mark unavailable", pos)
        menu = web.get("/app/menu/").content.decode()
        self.assertNotIn('label: "Available"', menu)
        self.assertNotIn("Available now", menu)
        self.assertNotIn("Limited quantity today", menu)
