from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import AuditLog, User
from apps.crm.models import Campaign, Customer
from apps.superadmin.models import get_settings
from apps.tenants.models import Restaurant


class SEOTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed", demo=True, stdout=open("/dev/null", "w"))
        cls.admin = User.objects.create_superuser("7000000000", "admin@example.com", "Adm1n-Passw0rd")

    def setUp(self):
        cache.clear()

    def test_platform_seo_settings_render(self):
        self.client.force_login(self.admin)
        res = self.client.post("/superadmin/settings/seo/", {"seo_title": "Servora POS", "seo_description": "Best restaurant POS", "seo_keywords": "pos, billing",
                                                             "og_image_url": "https://cdn.example.com/og.png", "allow_indexing": "on",
                                                             "google_site_verification": "abc123XYZ", "google_analytics_id": "G-TEST123", "meta_pixel_id": "123456789"})
        self.assertEqual(res.status_code, 302)
        self.client.logout()
        html = self.client.get("/").content.decode()
        for needle in ["<title>Servora POS</title>", 'content="Best restaurant POS"', "google-site-verification", "G-TEST123", "fbq('init','123456789')",
                       "https://cdn.example.com/og.png", '"@type": "SoftwareApplication"']:
            self.assertIn(needle, html)
        # app pages are never indexed and carry no analytics
        self.client.force_login(User.objects.get(username="9999999999"))
        app_html = self.client.get("/app/").content.decode()
        self.assertIn('content="noindex,nofollow"', app_html)
        self.assertNotIn("G-TEST123", app_html)

    def test_tracking_ids_validated(self):
        self.client.force_login(self.admin)
        res = self.client.post("/superadmin/settings/seo/", {"google_analytics_id": "G-1');alert(1);//", "allow_indexing": "on"})
        self.assertEqual(res.status_code, 200)  # form re-rendered with error
        self.assertEqual(get_settings(fresh=True).google_analytics_id, "")

    def test_robots_and_sitemap(self):
        robots = self.client.get("/robots.txt").content.decode()
        self.assertIn("Disallow: /app/", robots)
        self.assertIn("/sitemap.xml", robots)
        sm = self.client.get("/sitemap.xml").content.decode()
        self.assertIn("/s/spice-garden/", sm)
        ps = get_settings(fresh=True)
        ps.allow_indexing = False
        ps.save()
        self.assertIn("Disallow: /\n", self.client.get("/robots.txt").content.decode())

    def test_store_seo_and_jsonld(self):
        r = Restaurant.objects.get(slug="spice-garden")
        r.seo_title, r.cuisine, r.offer_banner = "Spice Garden — Kerala food in Kochi", "Kerala", "20% off today"
        r.save()
        html = self.client.get("/s/spice-garden/").content.decode()
        self.assertIn("<title>Spice Garden — Kerala food in Kochi</title>", html)
        self.assertIn('"@type": "Restaurant"', html)
        self.assertIn("20% off today", html)


class MarketingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed", demo=True, stdout=open("/dev/null", "w"))

    def setUp(self):
        cache.clear()
        self.c = APIClient()
        tok = self.c.post("/api/auth/login", {"phone": "9999999999", "password": "Demo@1234"}, format="json").json()["access"]
        self.c.credentials(HTTP_AUTHORIZATION="Bearer " + tok)
        self.r = Restaurant.objects.get(slug="spice-garden")

    def test_store_profile_edit_and_validation(self):
        res = self.c.patch("/api/marketing/store", {"seo_title": "Best biryani in Kochi", "instagram_url": "javascript:alert(1)"}, format="json")
        self.assertEqual(res.status_code, 400)
        res = self.c.patch("/api/marketing/store", {"seo_title": "Best biryani in Kochi", "google_review_url": "https://g.page/r/abc/review"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Restaurant.objects.get(pk=self.r.pk).seo_title, "Best biryani in Kochi")
        captain = APIClient()
        tok = captain.post("/api/auth/login", {"phone": "8888888801", "password": "Demo@1234"}, format="json").json()["access"]
        captain.credentials(HTTP_AUTHORIZATION="Bearer " + tok)
        self.assertEqual(captain.get("/api/marketing/store").status_code, 403)
        self.assertEqual(captain.get("/api/campaigns").status_code, 403)

    def test_email_campaign_segments_optout_and_batches(self):
        Customer.objects.filter(restaurant=self.r).update(email="")
        Customer.objects.filter(restaurant=self.r, phone="9876500001").update(email="rahul@example.com", visits=6)
        Customer.objects.filter(restaurant=self.r, phone="9876500002").update(email="priya@example.com", visits=1)
        Customer.objects.filter(restaurant=self.r, phone="9876500003").update(email="joseph@example.com", visits=8, marketing_opt_in=False)
        ps = get_settings(fresh=True)
        ps.email_enabled, ps.email_host, ps.site_url = True, "smtp.example.com", "https://servora.example"
        ps.save()
        camp = self.c.post("/api/campaigns", {"name": "Regulars treat", "channel": "email", "segment": "regulars", "subject": "A treat for you",
                                              "message": "Hi {name}, thanks for being a regular at {restaurant}! {link}"}, format="json").json()
        aud = self.c.post("/api/campaigns/audience", {"channel": "email", "segment": "regulars", "message": "Hi {name}"}, format="json").json()
        self.assertEqual(aud["count"], 1)  # opted-out regular excluded
        self.assertEqual(aud["sample"], "Hi Rahul")
        res = self.c.post(f"/api/campaigns/{camp['id']}/send", {}, format="json").json()
        self.assertEqual((res["sent"], res["remaining"]), (1, 0))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Hi Rahul, thanks for being a regular at Spice Garden! https://servora.example/s/spice-garden/", mail.outbox[0].body)
        self.assertIn("/unsubscribe/", mail.outbox[0].alternatives[0][0])
        # sending again doesn't double-send
        res = self.c.post(f"/api/campaigns/{camp['id']}/send", {}, format="json").json()
        self.assertEqual(res["sent"], 0)
        self.assertTrue(AuditLog.objects.filter(action="campaign.send").exists())
        self.assertEqual(Campaign.objects.get(pk=camp["id"]).status, "sent")

    def test_unsubscribe_link(self):
        from apps.crm.marketing import unsubscribe_token

        cust = Customer.objects.filter(restaurant=self.r).first()
        url = f"/unsubscribe/{unsubscribe_token(cust)}/"
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(url)
        cust.refresh_from_db()
        self.assertFalse(cust.marketing_opt_in)
        self.assertEqual(self.client.get("/unsubscribe/forged-token/").status_code, 404)

    def test_channel_not_configured(self):
        camp = self.c.post("/api/campaigns", {"name": "WA", "channel": "whatsapp", "segment": "all", "message": "Hi"}, format="json").json()
        res = self.c.post(f"/api/campaigns/{camp['id']}/send", {}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_marketing_page_renders(self):
        self.client.post("/login/", {"phone": "9999999999", "password": "Demo@1234"})
        self.assertEqual(self.client.get("/app/marketing/").status_code, 200)
