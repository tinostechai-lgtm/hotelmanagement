from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User


class EmailOrPhoneLoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed", demo=True, stdout=open("/dev/null", "w"))
        u = User.objects.get(username="9999999999")
        u.email = "Owner@SpiceGarden.example"
        u.save()
        cls.admin = User.objects.create_superuser("7000000000", "boss@servora.example", "Adm1n-Passw0rd")

    def setUp(self):
        cache.clear()

    def test_web_login_with_phone_variants_and_email(self):
        for ident in ["9999999999", "+91 99999 99999", "099999-99999", "owner@spicegarden.example", "  OWNER@SpiceGarden.example "]:
            self.client.logout()
            res = self.client.post("/login/", {"login": ident, "password": "Demo@1234"})
            self.assertRedirects(res, "/app/", msg_prefix=ident)
        self.client.logout()
        res = self.client.post("/login/", {"login": "owner@spicegarden.example", "password": "wrong"})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Incorrect mobile number / email or password")

    def test_api_login_with_email(self):
        c = APIClient()
        res = c.post("/api/auth/login", {"phone": "owner@spicegarden.example", "password": "Demo@1234"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("access", res.json())
        res = c.post("/api/auth/login", {"login": "+919999999999", "password": "Demo@1234"}, format="json")
        self.assertEqual(res.status_code, 200)

    def test_super_admin_login_page(self):
        self.assertContains(self.client.get("/superadmin/login/"), "Platform admin login")
        res = self.client.post("/superadmin/login/", {"login": "boss@servora.example", "password": "Adm1n-Passw0rd"})
        self.assertRedirects(res, "/superadmin/")
        self.client.logout()
        self.assertRedirects(self.client.get("/superadmin/payments/"), "/superadmin/login/?next=/superadmin/payments/", fetch_redirect_response=False)

    def test_signup_rejects_duplicate_email(self):
        res = APIClient().post("/api/auth/signup", {"name": "X Y", "phone": "9123456780", "email": "owner@spicegarden.example",
                                                    "password": "Passw0rd!", "restaurant_name": "Dup"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("email", res.json())
