"""Update list 3-5: live order details, bills after payment, daily item-wise report."""
from decimal import Decimal

from django.utils import timezone

from apps.operations.models import Table
from apps.tenants.models import Restaurant

from .test_flows import Base


class LiveBillsReportTests(Base):
    def setUp(self):
        super().setUp()
        Restaurant.objects.filter(pk=self.r.pk).update(gst_enabled=False, service_charge_percent=0)
        self.tables = list(Table.objects.filter(restaurant=self.r)[:2])
        self.tikka, self.coffee = self.item("Paneer Tikka"), self.item("Cold Coffee")

    def order(self, table, items):
        return self.c.post("/api/orders", {"table": table.id, "send_kot": True,
                                           "items": [{"item_id": i.id, "quantity": q} for i, q in items]}, format="json").json()

    def test_live_orders_include_item_details(self):
        self.order(self.tables[0], [(self.tikka, 2), (self.coffee, 1)])
        live = self.c.get("/api/orders/live?details=1").json()["orders"]
        o = live[0]
        self.assertEqual({(l["name"], l["qty"]) for l in o["lines"]}, {("Paneer Tikka", "2"), ("Cold Coffee", "1")})
        self.assertTrue(o["taken_by_name"])
        self.assertEqual(o["table_name"], self.tables[0].name)
        self.assertNotIn("lines", self.c.get("/api/orders/live").json()["orders"][0])  # lightweight by default

    def test_paid_bill_can_be_viewed_and_reprinted(self):
        o = self.order(self.tables[0], [(self.tikka, 1)])
        self.c.post(f"/api/orders/{o['id']}/pay", {"method": "upi", "reference": "UPI9"}, format="json")
        today = timezone.localdate().isoformat()
        bills = self.c.get(f"/api/bills?date={today}").json()
        bills = bills["results"] if isinstance(bills, dict) else bills
        b = next(x for x in bills if x["order_id"] == o["id"])
        self.assertEqual(b["status"], "paid")
        self.assertEqual(b["lines"][0]["name"], "Paneer Tikka")
        self.assertEqual(b["payments"][0]["method"], "upi")
        found = self.c.get(f"/api/bills?q={o['number']}").json()
        self.assertTrue((found["results"] if isinstance(found, dict) else found))
        res = self.c.post(f"/api/bills/{b['id']}/print", {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Paneer Tikka", res.json()["preview"])
        self.assertEqual(self.c.get(f"/api/bills/{b['id']}").status_code, 200)

    def test_daily_item_report(self):
        o1 = self.order(self.tables[0], [(self.tikka, 2), (self.coffee, 1)])
        o2 = self.order(self.tables[1], [(self.tikka, 1)])
        for o in (o1, o2):
            self.c.post(f"/api/orders/{o['id']}/pay", {"method": "cash"}, format="json")
        open_o = self.c.post("/api/orders", {"order_type": "takeaway", "items": [{"item_id": self.tikka.id, "quantity": 5}]}, format="json")
        self.assertEqual(open_o.status_code, 201)  # not paid -> not counted
        rep = self.c.get(f"/api/reports/items?date={timezone.localdate().isoformat()}").json()
        rows = {r["name"]: r for r in rep["items"]}
        self.assertEqual(Decimal(str(rows["Paneer Tikka"]["qty"])), 3)
        self.assertEqual(Decimal(str(rows["Paneer Tikka"]["amount"])), 3 * self.tikka.price)
        self.assertEqual(rows["Paneer Tikka"]["orders"], 2)
        self.assertEqual(Decimal(str(rows["Cold Coffee"]["qty"])), 1)
        self.assertEqual(Decimal(str(rep["total_qty"])), 4)
        self.assertEqual(Decimal(str(rep["total_amount"])), 3 * self.tikka.price + self.coffee.price)
        self.assertEqual(rep["orders"], 2)
        self.assertEqual(rep["items"][0]["name"], "Paneer Tikka")  # most sold first


class NewPagesRenderTests(Base):
    def test_live_bills_reports_pages(self):
        from django.test import Client

        web = Client()
        self.assertTrue(web.login(username="9999999999", password="Demo@1234"))
        for url, text in (("/app/live/", "Live orders"), ("/app/bills/", "Bill no., order no."), ("/app/reports/", "Daily item sales")):
            res = web.get(url)
            self.assertEqual(res.status_code, 200, url)
            self.assertContains(res, text)
