"""A second tap on Collect (slow network) must not record the payment twice."""
from apps.operations.models import Payment, Table

from .test_flows import Base


class PaymentGuardTests(Base):
    def test_second_payment_on_paid_bill_is_refused(self):
        t = Table.objects.filter(restaurant=self.r).first()
        item = self.item("Cold Coffee")
        o = self.c.post("/api/orders", {"table": t.id, "client_ref": "pay1", "send_kot": False,
                                        "items": [{"item_id": item.id, "quantity": 1}]}, format="json").json()
        first = self.c.post(f"/api/orders/{o['id']}/pay", {"method": "cash"}, format="json")
        self.assertIn(first.status_code, (200, 201), first.content)
        again = self.c.post(f"/api/orders/{o['id']}/pay", {"method": "cash"}, format="json")
        self.assertEqual(again.status_code, 400, again.content)
        self.assertEqual(Payment.objects.filter(order_id=o["id"], status="success").count(), 1)


class QAFixesTests(Base):
    def _order(self, **kw):
        body = {"order_type": "takeaway", "send_kot": True, "items": [{"item_id": self.item("Butter Chicken").id, "quantity": 1}]}
        body.update(kw)
        res = self.c.post("/api/orders", body, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        return res.json()

    def test_prepaid_takeaway_closes_when_kitchen_hands_it_over(self):
        o = self._order()
        self.c.post(f"/api/orders/{o['id']}/pay", {"method": "cash"}, format="json")
        o = self.c.get(f"/api/orders/{o['id']}").json()
        for k in o["kots"]:
            for st in ("ready", "served"):
                self.c.post(f"/api/kots/{k['id']}/status", {"status": st}, format="json")
        self.assertEqual(self.c.get(f"/api/orders/{o['id']}").json()["status"], "completed")

    def test_bill_is_refreshed_with_items_added_after_printing(self):
        t = Table.objects.filter(restaurant=self.r, orders__isnull=True).first()
        o = self.c.post("/api/orders", {"table": t.id, "client_ref": "b1", "items": [{"item_id": self.item("Butter Chicken").id, "quantity": 1}]}, format="json").json()
        self.c.post(f"/api/orders/{o['id']}/bill", {"print": False}, format="json")
        self.c.post(f"/api/orders/{o['id']}/items", {"client_ref": "b2", "items": [{"item_id": self.item("Cold Coffee").id, "quantity": 1}]}, format="json")
        self.c.post(f"/api/orders/{o['id']}/pay", {"method": "upi"}, format="json")
        fin = self.c.get(f"/api/orders/{o['id']}").json()
        self.assertTrue(fin["is_paid"], fin)
        self.assertEqual(fin["status"], "completed")

    def test_captain_cannot_close_unpaid_order(self):
        o = self._order()
        from rest_framework.test import APIClient
        cap = APIClient()
        tok = cap.post("/api/auth/login", {"phone": "8888888801", "password": "Demo@1234"}, format="json").json()["access"]
        cap.credentials(HTTP_AUTHORIZATION="Bearer " + tok)
        res = cap.post(f"/api/orders/{o['id']}/status", {"status": "completed"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_closed_order_cannot_be_changed_and_no_negative_discount(self):
        o = self._order()
        self.assertEqual(self.c.post(f"/api/orders/{o['id']}/discount", {"amount": -500}, format="json").status_code, 400)
        self.assertEqual(self.c.post(f"/api/orders/{o['id']}/discount", {"percent": 150}, format="json").status_code, 400)
        self.c.post(f"/api/orders/{o['id']}/pay", {"method": "cash"}, format="json")
        self.c.post(f"/api/orders/{o['id']}/status", {"status": "completed"}, format="json")
        line = o["items"][0]["id"]
        self.assertEqual(self.c.post(f"/api/orders/{o['id']}/items/{line}", {"void": True}, format="json").status_code, 400)

    def test_upi_overpay_refused_and_cancel_refunds(self):
        o = self._order()
        self.assertEqual(self.c.post(f"/api/orders/{o['id']}/pay", {"method": "upi", "amount": 99999}, format="json").status_code, 400)
        self.c.post(f"/api/orders/{o['id']}/pay", {"method": "cash"}, format="json")
        self.c.post(f"/api/orders/{o['id']}/status", {"status": "cancelled", "reason": "test"}, format="json")
        self.assertFalse(Payment.objects.filter(order_id=o["id"], status="success").exists())
        self.assertEqual(self.c.post(f"/api/orders/{o['id']}/pay", {"method": "cash"}, format="json").status_code, 400)

    def test_split_by_items_adds_up_with_packaging(self):
        o = self._order(items=[{"item_id": self.item("Butter Chicken").id, "quantity": 1}, {"item_id": self.item("Cold Coffee").id, "quantity": 1}])
        lines = [li["id"] for li in o["items"]]
        res = self.c.post(f"/api/orders/{o['id']}/split", {"mode": "items", "groups": [[lines[0]], [lines[1]]]}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        from decimal import Decimal
        from apps.operations.models import Bill, Order
        total = sum(b.total for b in Bill.objects.filter(order_id=o["id"]).exclude(status="void"))
        self.assertEqual(total, Order.objects.get(pk=o["id"]).total)
        self.assertGreater(Decimal(o["total"]), 0)

    def test_coupon_with_minimum_order_works_on_new_order(self):
        from apps.operations import services
        o = services.create_order(self.r, order_type="takeaway", source="online", customer_phone="9876500000",
                                  coupon_code="WELCOME20", items=[{"item_id": self.item("Butter Chicken").id, "quantity": 2}])
        self.assertGreater(o.discount, 0)
