from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase

from apps.operations.models import Table


class WebPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed", demo=True, stdout=open("/dev/null", "w"))
        from apps.accounts.models import User

        User.objects.create_superuser("7000000000", "admin@example.com", "Adm1n-Passw0rd")

    def setUp(self):
        cache.clear()

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


class QRTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed", demo=True, stdout=open("/dev/null", "w"))

    def test_short_qr_link_opens_table_mode(self):
        from apps.operations.models import Room

        t = Table.objects.first()
        res = self.client.get(f"/q/{t.qr_token}/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, f'"table": "{t.qr_token}"')
        room = Room.objects.first()
        self.assertContains(self.client.get(f"/q/{room.qr_token}/"), f'"room": "{room.qr_token}"')
        self.assertEqual(self.client.get("/q/not-a-real-token/").status_code, 404)

    def test_invalid_table_token_is_reported_not_delivery(self):
        data = self.client.get("/api/public/spice-garden/store?table=deleted-token").json()
        self.assertEqual(data.get("invalid_qr"), "table")
        self.assertNotIn("table", data)

    def test_qr_sheet_uses_short_links(self):
        self.client.post("/login/", {"login": "9999999999", "password": "Demo@1234"})
        html = self.client.get("/app/qr-codes/").content.decode()
        t = Table.objects.first()
        self.assertIn(f"/q/{t.qr_token}/", html)
        self.assertIn("not for tables", html)


class DownloadAppTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.accounts.models import User

        User.objects.create_superuser("7000000000", "a@example.com", "Adm1n-Passw0rd")

    def test_download_page_and_redirect(self):
        res = self.client.get("/download/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Android (APK)")
        self.assertContains(res, "/download/android")
        res = self.client.get("/download/android")
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res["Location"].endswith("/releases/latest/download/servora.apk"))
        self.assertContains(self.client.get("/"), "Download for Android")

    def test_super_admin_can_override_link(self):
        from apps.superadmin.models import get_settings

        ps = get_settings(fresh=True)
        ps.android_app_url = "https://play.google.com/store/apps/details?id=com.servora.servora"
        ps.save()
        self.assertEqual(self.client.get("/download/android")["Location"], ps.android_app_url)
        self.assertContains(self.client.get("/download/"), "Google Play")
