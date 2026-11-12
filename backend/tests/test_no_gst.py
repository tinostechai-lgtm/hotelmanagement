"""GST off (the default): no tax anywhere — order totals, bills, receipts, menu payload."""
from decimal import Decimal

from apps.hardware.services import render_bill
from apps.operations.models import Table
from apps.tenants.models import Restaurant

from .test_flows import Base


class NoGstTests(Base):
    def setUp(self):
        super().setUp()
        Restaurant.objects.filter(pk=self.r.pk).update(gst_enabled=False, service_charge_percent=0)
        self.r.refresh_from_db()

    def test_new_restaurants_do_not_charge_gst(self):
        self.assertFalse(Restaurant._meta.get_field("gst_enabled").default)

    def test_order_and_bill_have_no_gst(self):
        t = Table.objects.filter(restaurant=self.r).first()
        o = self.c.post("/api/orders", {"table": t.id, "items": [{"item_id": self.item("Paneer Tikka").id, "quantity": 2}]}, format="json").json()
        self.assertEqual(Decimal(o["tax"]), 0)
        self.assertEqual(Decimal(o["total"]), Decimal(o["subtotal"]))
        self.assertEqual(o["tax_breakup"], {})
        o = self.c.post(f"/api/orders/{o['id']}/bill", {}, format="json").json()
        from apps.operations.models import Bill
        bill = Bill.objects.filter(order_id=o["id"]).first()
        self.assertEqual(bill.tax, 0)
        text = render_bill(bill).plain
        self.assertNotIn("GST", text)
        self.assertNotIn("TAX INVOICE", text)

    def test_menu_reports_zero_gst(self):
        menu = self.c.get("/api/bootstrap").json()["menu"]
        rates = {i["tax_percent"] for c in menu for i in c["items"]}
        self.assertEqual(rates, {"0"})
