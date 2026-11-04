from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase

from apps.accounts.models import Membership, User
from apps.subscriptions.models import Plan
from apps.superadmin.models import PlatformAuditLog, PlatformRole, PlatformStaff
from apps.tenants.models import Restaurant


class PlatformRBACTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed", demo=True, stdout=open("/dev/null", "w"))
        cls.admin = User.objects.create_superuser("7000000000", "admin@example.com", "Adm1n-Passw0rd")
        cls.support_user = User.objects.create_user("7000000001", password="Support-Passw0rd")
        PlatformStaff.objects.create(user=cls.support_user, role=PlatformRole.objects.get(name="Support"))
        cls.finance_user = User.objects.create_user("7000000002", password="Finance-Passw0rd")
        PlatformStaff.objects.create(user=cls.finance_user, role=PlatformRole.objects.get(name="Finance"))
        cls.r = Restaurant.objects.get(slug="spice-garden")

    def setUp(self):
        cache.clear()

    def test_support_role_limits(self):
        self.client.force_login(self.support_user)
        self.assertEqual(self.client.get("/superadmin/").status_code, 200)
        self.assertEqual(self.client.get("/superadmin/restaurants/").status_code, 200)
        self.assertEqual(self.client.get("/superadmin/settings/payments/").status_code, 403)  # no API keys for support
        self.assertEqual(self.client.get("/superadmin/team/").status_code, 403)
        self.assertEqual(self.client.get("/superadmin/payments/").status_code, 403)
        # allowed: extend; not allowed: suspend
        before = self.r.subscription.current_period_end
        self.client.post(f"/superadmin/restaurants/{self.r.pk}/", {"action": "extend", "days": "7"})
        self.assertGreater(Restaurant.objects.get(pk=self.r.pk).subscription.current_period_end, before)
        self.client.post(f"/superadmin/restaurants/{self.r.pk}/", {"action": "suspend", "reason": "x"})
        self.assertTrue(Restaurant.objects.get(pk=self.r.pk).is_active)
        self.assertTrue(PlatformAuditLog.objects.filter(action="restaurant.extend", user=self.support_user).exists())

    def test_finance_cannot_change_restaurants(self):
        self.client.force_login(self.finance_user)
        self.assertEqual(self.client.get("/superadmin/payments/").status_code, 200)
        before = self.r.subscription.current_period_end
        self.client.post(f"/superadmin/restaurants/{self.r.pk}/", {"action": "extend", "days": "30"})
        self.assertEqual(Restaurant.objects.get(pk=self.r.pk).subscription.current_period_end, before)

    def test_restaurant_owner_has_no_platform_access(self):
        self.client.force_login(User.objects.get(username="9999999999"))
        self.assertEqual(self.client.get("/superadmin/").status_code, 404)

    def test_disabled_staff_loses_access(self):
        PlatformStaff.objects.filter(user=self.support_user).update(is_active=False)
        self.client.force_login(self.support_user)
        self.assertEqual(self.client.get("/superadmin/").status_code, 404)

    def test_add_client_creates_restaurant_owner_and_plan(self):
        self.client.force_login(self.support_user)
        res = self.client.post("/superadmin/restaurants/new/", {
            "restaurant_name": "Hotel Blue Lagoon", "business_type": "hotel", "city": "Munnar", "owner_name": "Anil K",
            "owner_phone": "9555555555", "owner_email": "anil@example.com", "password": "", "plan": Plan.objects.get(code="pro").pk,
            "status": "active", "days": 365, "send_email": ""})
        r = Restaurant.objects.get(name="Hotel Blue Lagoon")
        self.assertRedirects(res, f"/superadmin/restaurants/{r.pk}/")
        sub = r.subscription
        self.assertEqual((sub.plan.code, sub.status, sub.cycle), ("pro", "active", "yearly"))
        self.assertEqual(Membership.objects.get(restaurant=r).role.name, "Owner")
        self.assertTrue(PlatformAuditLog.objects.filter(action="client.create").exists())

    def test_add_user_to_restaurant_and_reset_password(self):
        self.client.force_login(self.support_user)
        from apps.accounts.models import Role

        cashier = Role.objects.get(restaurant=self.r, name="Cashier")
        self.client.post(f"/superadmin/restaurants/{self.r.pk}/", {"action": "add_user", "name": "New Cashier", "phone": "9666666666",
                                                                   "email": "", "role": cashier.pk, "password": "Cashier-123"})
        u = User.objects.get(username="9666666666")
        self.assertTrue(Membership.objects.filter(user=u, restaurant=self.r, role=cashier).exists())
        self.assertTrue(u.check_password("Cashier-123"))
        self.client.post(f"/superadmin/restaurants/{self.r.pk}/", {"action": "reset_password", "user": u.pk})
        u.refresh_from_db()
        self.assertFalse(u.check_password("Cashier-123"))

    def test_role_escalation_blocked(self):
        # Give support the team permission but not settings; it must not create a role with settings.
        role = PlatformRole.objects.get(name="Support")
        role.permissions = role.permissions + ["team"]
        role.save()
        self.client.force_login(self.support_user)
        self.client.post("/superadmin/team/roles/new/", {"name": "Sneaky", "description": "", "permissions": ["settings"]})
        self.assertFalse(PlatformRole.objects.filter(name="Sneaky").exists())
        # and can't assign the Administrator role to anyone
        self.client.post("/superadmin/team/", {"action": "add", "name": "X", "phone": "9777777777", "email": "",
                                               "role": PlatformRole.objects.get(name="Administrator").pk, "password": "Long-Passw0rd"})
        self.assertFalse(PlatformStaff.objects.filter(user__username="9777777777").exists())
        # super admin promotion is superuser-only
        target = User.objects.get(username="8888888801")
        self.client.post("/superadmin/users/", {"user": target.pk, "action": "toggle_superuser"})
        target.refresh_from_db()
        self.assertFalse(target.is_superuser)

    def test_superadmin_can_add_team_member(self):
        self.client.force_login(self.admin)
        self.client.post("/superadmin/team/", {"action": "add", "name": "Sales Person", "phone": "9888888888", "email": "",
                                               "role": PlatformRole.objects.get(name="Sales").pk, "password": "Long-Passw0rd"})
        staff = PlatformStaff.objects.get(user__username="9888888888")
        self.assertEqual(staff.role.name, "Sales")
        self.client.logout()
        res = self.client.post("/login/", {"phone": "9888888888", "password": "Long-Passw0rd"})
        self.assertRedirects(res, "/superadmin/")
        for url in ["/superadmin/team/", "/superadmin/activity/"]:
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_all_pages_render_for_admin(self):
        self.client.force_login(self.admin)
        for url in ["/superadmin/team/", "/superadmin/team/roles/new/", f"/superadmin/team/roles/{PlatformRole.objects.first().pk}/",
                    "/superadmin/activity/", "/superadmin/restaurants/new/", f"/superadmin/restaurants/{self.r.pk}/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
