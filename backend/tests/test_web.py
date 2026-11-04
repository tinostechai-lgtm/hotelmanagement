from django.core.management import call_command
from django.test import TestCase

from apps.operations.models import Table


class WebPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed", demo=True, stdout=open("/dev/null", "w"))

    def test_public_pages(self):
        for url in ["/", "/login/", "/signup/", "/s/spice-garden/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertContains(self.client.get("/"), "Kitchen Order Tickets")

    def test_app_pages_render_for_owner(self):
        self.client.post("/login/", {"phone": "9999999999", "password": "Demo@1234"})
        for page in ["", "pos/", "orders/", "kitchen/", "delivery/", "menu/", "floor/", "customers/", "inventory/", "reports/",
                     "staff/", "hardware/", "settings/", "billing/", "qr-codes/"]:
            res = self.client.get("/app/" + page)
            self.assertEqual(res.status_code, 200, page)
        t = Table.objects.first()
        self.assertContains(self.client.get("/app/qr-codes/"), t.qr_token)

    def test_kitchen_user_restricted(self):
        self.client.post("/login/", {"phone": "8888888803", "password": "Demo@1234"})
        self.assertEqual(self.client.get("/app/kitchen/").status_code, 200)
        self.assertEqual(self.client.get("/app/reports/").status_code, 403)

    def test_signup_web(self):
        res = self.client.post("/signup/", {"name": "A B", "phone": "9000011111", "password": "Passw0rd!", "restaurant_name": "Cafe X", "business_type": "cafe"})
        self.assertRedirects(res, "/app/")
        self.assertEqual(self.client.get("/app/").status_code, 200)
