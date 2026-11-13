"""Each crew member has their own login, and a crew login works on one phone at a time."""
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Role, User

from .test_flows import Base


class OneDeviceLoginTests(Base):
    def setUp(self):
        super().setUp()
        u = User.objects.create_user(username="7200000001", phone="7200000001", first_name="Anil", password="Pass@1234")
        Membership.objects.create(user=u, restaurant=self.r, role=Role.objects.get(restaurant=self.r, name="Captain"))

    def login(self, phone, password, device):
        c = APIClient()
        res = c.post("/api/auth/login", {"phone": phone, "password": password}, format="json", HTTP_X_DEVICE_ID=device)
        self.assertEqual(res.status_code, 200, res.content)
        c.credentials(HTTP_AUTHORIZATION="Bearer " + res.json()["access"], HTTP_X_DEVICE_ID=device)
        return c

    def test_crew_login_moves_to_the_newest_phone(self):
        p1 = self.login("7200000001", "Pass@1234", "phone-1")
        self.assertEqual(p1.get("/api/tables").status_code, 200)
        p2 = self.login("7200000001", "Pass@1234", "phone-2")  # same login used on a second phone
        self.assertEqual(p2.get("/api/tables").status_code, 200)
        res = p1.get("/api/tables")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["code"], "signed_in_elsewhere")
        self.assertIn("own login", res.json()["detail"])

    def test_owner_can_use_several_devices(self):
        a = self.login("9999999999", "Demo@1234", "laptop")
        b = self.login("9999999999", "Demo@1234", "phone")
        self.assertEqual(a.get("/api/tables").status_code, 200)
        self.assertEqual(b.get("/api/tables").status_code, 200)

    def test_requests_without_device_id_still_work(self):
        p1 = self.login("7200000001", "Pass@1234", "phone-1")
        c = APIClient()
        tok = c.post("/api/auth/login", {"phone": "7200000001", "password": "Pass@1234"}, format="json").json()["access"]
        c.credentials(HTTP_AUTHORIZATION="Bearer " + tok)  # old app: no device id
        self.assertEqual(c.get("/api/tables").status_code, 200)
        self.assertEqual(p1.get("/api/tables").status_code, 200)
