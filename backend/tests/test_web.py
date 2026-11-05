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
        self.assertContains(res, "/get/")
        page = self.client.get("/get/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "/downloads/servora.apk")
        self.assertContains(page, "Download again")
        res = self.client.get("/download/android")
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res["Location"], "/downloads/servora.apk")
        apk = self.client.get("/downloads/servora.apk")
        self.assertEqual(apk.status_code, 200)
        self.assertEqual(apk["Content-Type"], "application/vnd.android.package-archive")
        self.assertIn('attachment; filename="Servora.apk"', apk["Content-Disposition"])
        self.assertEqual(self.client.get("/downloads/android.json").status_code, 200)
        self.assertEqual(self.client.get("/downloads/secret.txt").status_code, 404)
        self.assertContains(self.client.get("/"), "Download for Android")

    def test_super_admin_can_override_link(self):
        from apps.superadmin.models import get_settings

        ps = get_settings(fresh=True)
        ps.android_app_url = "https://play.google.com/store/apps/details?id=com.servora.servora"
        ps.save()
        self.assertEqual(self.client.get("/download/android")["Location"], ps.android_app_url)
        self.assertContains(self.client.get("/download/"), "Google Play")
        self.assertEqual(self.client.get("/get/")["Location"], ps.android_app_url)


class IosAppLinkTests(TestCase):
    IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1"

    def setUp(self):
        from apps.superadmin.models import get_settings

        cache.clear()
        get_settings(fresh=True)  # drop the per-process settings cache left by other tests

    def test_iphone_gets_home_screen_install_page(self):
        res = self.client.get("/get/", HTTP_USER_AGENT=self.IPHONE)  # same QR as Android
        self.assertRedirects(res, "/get/ios/", fetch_redirect_response=False)
        page = self.client.get("/get/ios/", HTTP_USER_AGENT=self.IPHONE)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Add to Home Screen")
        dl = self.client.get("/download/")
        self.assertContains(dl, 'id="ios-btn"')
        self.assertContains(dl, "/get/ios/")

    def test_iphone_link_from_super_admin(self):
        from apps.superadmin.models import get_settings

        ps = get_settings()
        ps.ios_app_url = "https://testflight.apple.com/join/AbCdEf12"
        ps.save()
        get_settings(fresh=True)
        self.assertEqual(self.client.get("/get/ios/")["Location"], ps.ios_app_url)
        # Android phones still get the APK page
        self.assertEqual(self.client.get("/get/", HTTP_USER_AGENT="Mozilla/5.0 (Linux; Android 14)").status_code, 200)
        self.assertContains(self.client.get("/download/"), "iPhone (TestFlight)")
