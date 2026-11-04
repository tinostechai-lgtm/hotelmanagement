from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import AuditLog, Membership, Role, User
from apps.menu.models import Item
from apps.tenants.models import Restaurant


def client_for(phone):
    c = APIClient()
    tok = c.post("/api/auth/login", {"phone": phone, "password": "Demo@1234"}, format="json").json()["access"]
    c.credentials(HTTP_AUTHORIZATION="Bearer " + tok)
    return c


class RestaurantRBACTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed", demo=True, stdout=open("/dev/null", "w"))
        cls.r = Restaurant.objects.get(slug="spice-garden")
        mgr = User.objects.create_user("8888888809", password="Demo@1234", first_name="Mona")
        Membership.objects.create(user=mgr, restaurant=cls.r, role=Role.objects.get(restaurant=cls.r, name="Manager"))

    def setUp(self):
        cache.clear()
        self.owner = client_for("9999999999")
        self.manager = client_for("8888888809")

    def role(self, name):
        return Role.objects.get(restaurant=self.r, name=name)

    def test_owner_role_is_locked(self):
        res = self.owner.patch(f"/api/roles/{self.role('Owner').id}", {"permissions": ["pos"]}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("billing", self.role("Owner").permissions)

    def test_manager_cannot_escalate(self):
        # Manager lacks "billing": can't grant it to a role, can't create a role with it, can't assign Owner.
        res = self.manager.patch(f"/api/roles/{self.role('Cashier').id}", {"permissions": ["pos", "billing"]}, format="json")
        self.assertEqual(res.status_code, 400)
        res = self.manager.post("/api/roles", {"name": "Sneaky", "permissions": ["billing"]}, format="json")
        self.assertEqual(res.status_code, 400)
        res = self.manager.post("/api/staff", {"name": "X", "phone": "9123400000", "role": self.role("Owner").id}, format="json")
        self.assertEqual(res.status_code, 403)
        cashier_m = Membership.objects.get(user__username="8888888802")
        res = self.manager.patch(f"/api/staff/{cashier_m.id}", {"role": self.role("Owner").id}, format="json")
        self.assertEqual(res.status_code, 403)
        owner_m = Membership.objects.get(user__username="9999999999")
        res = self.manager.patch(f"/api/staff/{owner_m.id}", {"is_active": False}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_manager_can_grant_within_own_permissions_and_it_is_logged(self):
        res = self.manager.patch(f"/api/roles/{self.role('Captain').id}", {"permissions": ["pos", "discount"]}, format="json")
        self.assertEqual(res.status_code, 200)
        log = AuditLog.objects.get(action="role.update")
        self.assertIn("discount", log.detail)
        self.assertEqual(self.owner.get("/api/activity").status_code, 200)

    def test_custom_role_enforced(self):
        res = self.owner.post("/api/roles", {"name": "Menu Editor", "permissions": ["menu"]}, format="json")
        self.assertEqual(res.status_code, 201)
        self.owner.post("/api/staff", {"name": "Editor", "phone": "9123400001", "role": res.json()["id"], "password": "Demo@1234"}, format="json")
        editor = client_for("9123400001")
        item = Item.objects.filter(restaurant=self.r).first()
        self.assertEqual(editor.patch(f"/api/items/{item.id}", {"price": "999"}, format="json").status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action="menu.price", target=item.name).exists())
        self.assertEqual(editor.post("/api/orders", {"order_type": "takeaway"}, format="json").status_code, 403)
        self.assertEqual(editor.get("/api/customers").status_code, 403)
        self.assertEqual(editor.get("/api/reports/summary").status_code, 403)

    def test_captain_customer_access(self):
        captain = client_for("8888888801")
        self.assertEqual(captain.get("/api/customers").status_code, 403)  # no bulk customer list
        self.assertEqual(captain.get("/api/customers/lookup?phone=9876500001").status_code, 200)  # single lookup while billing
        self.assertEqual(captain.get("/api/shifts").status_code, 403)
        self.assertEqual(captain.post("/api/devices/open-drawer", {}, format="json").status_code, 403)

    def test_void_and_discount_are_audited(self):
        item = Item.objects.get(restaurant=self.r, name="Masala Chai")
        o = self.owner.post("/api/orders", {"order_type": "takeaway", "items": [{"item_id": item.id, "quantity": 2}], "send_kot": True}, format="json").json()
        self.owner.post(f"/api/orders/{o['id']}/discount", {"percent": 10, "reason": "Regular"}, format="json")
        self.owner.post(f"/api/orders/{o['id']}/items/{o['items'][0]['id']}", {"void": True, "reason": "Wrong item"}, format="json")
        actions = set(AuditLog.objects.filter(restaurant=self.r).values_list("action", flat=True))
        self.assertTrue({"order.discount", "order.void_item"} <= actions)

    def test_staff_page_renders_for_manager(self):
        c = self.client
        c.post("/login/", {"phone": "8888888809", "password": "Demo@1234"})
        self.assertEqual(c.get("/app/staff/").status_code, 200)
