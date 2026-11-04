from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.subscriptions import razorpay_client
from apps.subscriptions.models import Plan
from apps.superadmin.models import get_settings
from apps.tenants.models import Restaurant


class SetupTests(TestCase):
    def setUp(self):
        cache.clear()
        call_command("seed", stdout=open("/dev/null", "w"))

    def test_first_run_setup_then_locked(self):
        self.assertRedirects(self.client.get("/"), "/setup/")
        res = self.client.post("/setup/", {"name": "Tino M", "phone": "9000000001", "email": "owner@example.com",
                                           "password": "very-strong-pass", "site_url": "https://servora.example"})
        self.assertRedirects(res, "/superadmin/")
        self.assertTrue(User.objects.get(username="9000000001").is_superuser)
        self.assertEqual(get_settings(fresh=True).site_url, "https://servora.example")
        # setup is closed once a super admin exists
        self.client.logout()
        self.assertRedirects(self.client.get("/setup/"), "/login/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_healthz(self):
        res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["db_connection"], "ok")
        self.assertEqual(res.json()["pending_migrations"], 0)


class SuperAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed", demo=True, stdout=open("/dev/null", "w"))
        cls.admin = User.objects.create_superuser("7000000000", "admin@example.com", "Adm1n-Passw0rd")

    def setUp(self):
        cache.clear()
        self.client.force_login(self.admin)

    def test_pages_render(self):
        r = Restaurant.objects.get(slug="spice-garden")
        for url in ["/superadmin/", "/superadmin/restaurants/", f"/superadmin/restaurants/{r.pk}/", "/superadmin/plans/",
                    "/superadmin/plans/new/", f"/superadmin/plans/{Plan.objects.first().pk}/", "/superadmin/payments/", "/superadmin/users/"] + \
                [f"/superadmin/settings/{s}/" for s in ["general", "signup", "payments", "email", "sms", "integrations"]]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_non_superuser_blocked(self):
        self.client.force_login(User.objects.get(username="9999999999"))
        self.assertEqual(self.client.get("/superadmin/").status_code, 404)
        self.assertEqual(self.client.get("/superadmin/settings/payments/").status_code, 404)

    def test_razorpay_keys_saved_encrypted_and_used(self):
        res = self.client.post("/superadmin/settings/payments/", {"razorpay_key_id": "rzp_test_abc", "razorpay_key_secret": "s3cret-value",
                                                                  "razorpay_webhook_secret": "wh-secret"})
        self.assertEqual(res.status_code, 302)
        with connection.cursor() as c:
            c.execute("SELECT razorpay_key_secret FROM superadmin_platformsettings WHERE id=1")
            raw = c.fetchone()[0]
        self.assertTrue(raw.startswith("enc:"))
        self.assertNotIn("s3cret-value", raw)
        ps = get_settings(fresh=True)
        self.assertEqual(ps.razorpay_key_secret, "s3cret-value")
        self.assertTrue(razorpay_client.enabled())
        self.assertEqual(razorpay_client.key_id(), "rzp_test_abc")
        # blank secret on re-save keeps the stored value
        self.client.post("/superadmin/settings/payments/", {"razorpay_key_id": "rzp_test_abc", "razorpay_key_secret": "", "razorpay_webhook_secret": ""})
        self.assertEqual(get_settings(fresh=True).razorpay_key_secret, "s3cret-value")
        # explicit clear removes it
        self.client.post("/superadmin/settings/payments/", {"razorpay_key_id": "", "razorpay_key_secret": "", "razorpay_key_secret__clear": "on",
                                                            "razorpay_webhook_secret": ""})
        self.assertFalse(razorpay_client.enabled())

    def test_email_test_and_welcome_email(self):
        self.client.post("/superadmin/settings/email/", {"email_enabled": "on", "email_host": "smtp.example.com", "email_port": 587,
                                                         "email_use_tls": "on", "email_username": "u", "email_password": "p",
                                                         "email_from": "hello@example.com", "email_from_name": "Servora"})
        self.client.post("/superadmin/test/email/", {"to": "me@example.com"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Test email", mail.outbox[0].subject)
        with self.captureOnCommitCallbacks(execute=True):
            APIClient().post("/api/auth/signup", {"name": "New Owner", "phone": "9333333333", "email": "new@example.com",
                                                  "password": "Passw0rd!", "restaurant_name": "Bistro"}, format="json")
        self.assertTrue(any("Welcome" in m.subject for m in mail.outbox))

    def test_signup_toggle_and_trial_settings(self):
        ps = get_settings(fresh=True)
        ps.signup_enabled = False
        ps.save()
        res = APIClient().post("/api/auth/signup", {"name": "A", "phone": "9444444444", "password": "Passw0rd!", "restaurant_name": "X"}, format="json")
        self.assertEqual(res.status_code, 403)
        ps.signup_enabled, ps.trial_days, ps.trial_plan = True, 30, Plan.objects.get(code="growth")
        ps.save()
        APIClient().post("/api/auth/signup", {"name": "A", "phone": "9444444444", "password": "Passw0rd!", "restaurant_name": "X"}, format="json")
        sub = Restaurant.objects.get(name="X").subscription
        self.assertEqual(sub.plan.code, "growth")
        self.assertIn(sub.days_left, (29, 30))

    def test_suspend_restaurant(self):
        r = Restaurant.objects.get(slug="spice-garden")
        self.client.post(f"/superadmin/restaurants/{r.pk}/", {"action": "suspend", "reason": "Payment overdue"})
        r.refresh_from_db()
        self.assertFalse(r.is_active)
        self.assertEqual(self.client.get("/s/spice-garden/").status_code, 404)
        owner = APIClient()
        tok = owner.post("/api/auth/login", {"phone": "9999999999", "password": "Demo@1234"}, format="json").json()["access"]
        owner.credentials(HTTP_AUTHORIZATION="Bearer " + tok)
        self.assertEqual(owner.get("/api/orders").status_code, 403)
        self.client.post(f"/superadmin/restaurants/{r.pk}/", {"action": "activate"})
        r.refresh_from_db()
        self.assertTrue(r.is_active)

    def test_extend_and_edit_plan(self):
        r = Restaurant.objects.get(slug="spice-garden")
        before = r.subscription.current_period_end
        self.client.post(f"/superadmin/restaurants/{r.pk}/", {"action": "extend", "days": "30"})
        self.assertGreater(Restaurant.objects.get(pk=r.pk).subscription.current_period_end, before)
        p = Plan.objects.get(code="starter")
        res = self.client.post(f"/superadmin/plans/{p.pk}/", {"code": "starter", "name": "Starter", "tagline": "x", "price_monthly": "799",
                                                              "price_yearly": "7990", "max_users": 3, "max_devices": 2, "max_outlets": 1,
                                                              "features": ["pos", "kot"], "is_public": "on", "sort": 1})
        self.assertEqual(res.status_code, 302)
        p.refresh_from_db()
        self.assertEqual((str(p.price_monthly), p.features), ("799.00", ["pos", "kot"]))
        call_command("seed", stdout=open("/dev/null", "w"))  # re-seeding must not undo the edit
        p.refresh_from_db()
        self.assertEqual(str(p.price_monthly), "799.00")

    def test_password_reset_by_phone(self):
        u = User.objects.get(username="9999999999")
        u.email = "owner@spice.example"
        u.save()
        get_settings(fresh=True)
        self.client.logout()
        res = self.client.post("/password-reset/", {"email": "9999999999"})
        self.assertRedirects(res, "/password-reset/sent/")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/password-reset/", mail.outbox[0].body)
