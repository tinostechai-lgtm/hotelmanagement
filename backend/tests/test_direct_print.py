"""Direct printing: jobs carry their KOT / bill, can be claimed once, and re-rendered for any paper / text size."""
import base64

from apps.hardware.escpos import Receipt
from apps.hardware.models import Device, PrintJob
from apps.operations.models import Table

from .test_flows import Base


class DirectPrintTests(Base):
    def _kot_order(self):
        t = Table.objects.filter(restaurant=self.r, orders__isnull=True).first()
        res = self.c.post("/api/orders", {"table": t.id, "client_ref": "dp1", "send_kot": True,
                                          "items": [{"item_id": self.item("Butter Chicken").id, "quantity": 2}]}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        return res.json()

    def test_kot_jobs_can_be_found_claimed_once_and_rendered(self):
        o = self._kot_order()
        jobs = self.c.get(f"/api/print-jobs?status=queued&order={o['id']}&kind=kot&since=180").json()
        jobs = jobs.get("results", jobs) if isinstance(jobs, dict) else jobs
        self.assertTrue(jobs)
        j = jobs[0]
        self.assertTrue(j["source"].startswith("kot:"))
        self.assertEqual(self.c.post(f"/api/print-jobs/{j['id']}/claim", {}, format="json").status_code, 200)
        self.assertEqual(self.c.post(f"/api/print-jobs/{j['id']}/claim", {}, format="json").status_code, 409)  # 2nd phone
        r58 = self.c.get(f"/api/print-jobs/{j['id']}/render?width=58&size=large").json()
        self.assertEqual(r58["columns"], 32)
        self.assertIn("Butter Chicken", r58["text"])
        raw = base64.b64decode(r58["escpos_b64"])
        self.assertIn(b"\x1d!\x01", raw)  # double-height letters
        xl = self.c.get(f"/api/print-jobs/{j['id']}/render?width=80&size=xlarge").json()
        self.assertEqual(xl["columns"], 24)
        web = self.c.get(f"/api/print-jobs/{j['id']}/render?width=80&size=large&columns=32").json()
        self.assertEqual(web["columns"], 32)
        self.assertTrue(any(line.get("big") for line in web["lines"]))
        self.c.post(f"/api/print-jobs/{j['id']}/ack", {"ok": True}, format="json")
        self.assertEqual(PrintJob.objects.get(pk=j["id"]).status, "done")

    def test_bill_job_links_to_order_and_device_text_size_is_used(self):
        d = Device.objects.filter(restaurant=self.r, kind="receipt_printer").first() or Device.objects.create(
            restaurant=self.r, name="Counter", kind="receipt_printer")
        res = self.c.patch(f"/api/devices/{d.id}", {"text_size": "large", "paper_width": 58}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["text_size"], "large")
        Device.objects.filter(restaurant=self.r, kind="receipt_printer").exclude(pk=d.pk).update(is_active=False)
        o = self._kot_order()
        self.c.post(f"/api/orders/{o['id']}/bill", {}, format="json")
        job = PrintJob.objects.filter(order_id=o["id"], kind="bill").latest("id")
        self.assertTrue(job.source.startswith("bill:"))
        self.assertIn(b"\x1d!\x01", base64.b64decode(job.escpos_b64))
        self.assertTrue(all(len(line) <= 32 for line in job.text.splitlines()))

    def test_receipt_sizes(self):
        self.assertEqual(Receipt(80).w, 48)
        self.assertEqual(Receipt(58).w, 32)
        self.assertEqual(Receipt(80, "xlarge").w, 24)
        self.assertEqual(Receipt(80, "large").w, 48)
