from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

User = get_user_model()


class DirectorAccessTests(APITestCase):
    """Роль «Директор» — read-only, только отчёты своего направления."""

    def setUp(self):
        self.dir_ex = User.objects.create_user(
            "dir_ex", password="pass1234", role=User.Role.DIRECTOR, module="EXPRESS"
        )
        self.dir_bz = User.objects.create_user(
            "dir_bz", password="pass1234", role=User.Role.DIRECTOR, module="BUSINESS"
        )

    def test_director_blocked_from_data_endpoints(self):
        self.client.force_authenticate(self.dir_ex)
        for url in ("/api/expenses/", "/api/accounts/", "/api/reports/balances/",
                    "/api/reports/journal/", "/api/deposits/", "/api/settings/",
                    "/api/sales/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_director_allowed_reports(self):
        self.client.force_authenticate(self.dir_ex)
        for url in ("/api/reports/pnl/", "/api/reports/cashflow/",
                    "/api/reports/monthly/", "/api/reports/breakdown/?line=opex"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_director_module_is_forced(self):
        # Директор Express, даже прося module=BUSINESS, получает свой раздел.
        self.client.force_authenticate(self.dir_ex)
        r = self.client.get("/api/reports/pnl/?module=BUSINESS&from=2020-01-01&to=2030-01-01")
        self.assertEqual(r.status_code, 200)
        # deposit_revenue (Business) не должен «протечь» директору Express.
        self.assertEqual(r.data["deposit_revenue"], 0)

    def test_director_can_read_own_profile(self):
        self.client.force_authenticate(self.dir_bz)
        r = self.client.get("/api/users/me/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["role"], "DIRECTOR")
        self.assertEqual(r.data["module"], "BUSINESS")


class UserManagementTests(APITestCase):
    """Админ управляет пользователями; директор обязан иметь направление."""

    def setUp(self):
        self.admin = User.objects.create_user("admin3", password="pass1234", role=User.Role.ADMIN)
        self.client.force_authenticate(self.admin)

    def test_create_director_requires_module(self):
        r = self.client.post("/api/users/", {
            "username": "d1", "role": "DIRECTOR", "password": "pass1234",
        }, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("module", r.data)

    def test_create_director_with_module(self):
        r = self.client.post("/api/users/", {
            "username": "d2", "role": "DIRECTOR", "module": "EXPRESS", "password": "pass1234",
        }, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(User.objects.get(username="d2").module, "EXPRESS")

    def test_manager_module_cleared(self):
        r = self.client.post("/api/users/", {
            "username": "m1", "role": "MANAGER", "module": "EXPRESS", "password": "pass1234",
        }, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertIsNone(User.objects.get(username="m1").module)

    def test_admin_can_delete_user(self):
        victim = User.objects.create_user("victim", password="pass1234", role=User.Role.MANAGER)
        r = self.client.delete(f"/api/users/{victim.id}/")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(User.objects.filter(username="victim").exists())
