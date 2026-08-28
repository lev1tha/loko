from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APITestCase

from finance.models import Branch

User = get_user_model()

# The configured per-IP login limit (e.g. "10/min") — read straight from settings
# so the test tracks the real production value instead of hard-coding it.
_LOGIN_LIMIT = int(settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"].split("/")[0])


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
            "username": "d1", "role": "DIRECTOR", "password": "Zx9!mfP2qL",
        }, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("module", r.data)

    def test_create_director_with_module(self):
        r = self.client.post("/api/users/", {
            "username": "d2", "role": "DIRECTOR", "module": "EXPRESS", "password": "Zx9!mfP2qL",
        }, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(User.objects.get(username="d2").module, "EXPRESS")

    def test_manager_module_cleared(self):
        r = self.client.post("/api/users/", {
            "username": "m1", "role": "MANAGER", "module": "EXPRESS", "password": "Zx9!mfP2qL",
        }, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertIsNone(User.objects.get(username="m1").module)

    def test_admin_can_delete_user(self):
        victim = User.objects.create_user("victim", password="pass1234", role=User.Role.MANAGER)
        r = self.client.delete(f"/api/users/{victim.id}/")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(User.objects.filter(username="victim").exists())


class BranchAssignmentTests(APITestCase):
    """Филиал назначается «Сотруднику» И «Складовщику»; у прочих ролей — очищается.

    Симметрия ролей: и продажа сотрудника, и заявки склада привязаны к филиалу,
    поэтому оба должны уметь его хранить (ранее склад терял филиал → пустая доска).
    """

    def setUp(self):
        self.admin = User.objects.create_user("admin_br", password="pass1234", role=User.Role.ADMIN)
        self.client.force_authenticate(self.admin)
        self.branch = Branch.objects.create(name="Раззакова", is_default=False)

    def _create(self, username, role):
        return self.client.post("/api/users/", {
            "username": username, "role": role,
            "branch": self.branch.id, "password": "Zx9!mfP2qL",
        }, format="json")

    def test_operator_keeps_branch(self):
        r = self._create("op1", "OPERATOR")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(User.objects.get(username="op1").branch_id, self.branch.id)

    def test_warehouse_keeps_branch(self):
        # Раньше сериализатор обнулял филиал у склада → складовщик не видел заявок.
        r = self._create("wh1", "WAREHOUSE")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(User.objects.get(username="wh1").branch_id, self.branch.id)

    def test_manager_branch_cleared(self):
        # У ролей без привязки к филиалу он по-прежнему очищается.
        r = self._create("mg1", "MANAGER")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIsNone(User.objects.get(username="mg1").branch_id)

    def test_warehouse_branch_editable_inline(self):
        # Inline-правка филиала складовщика в таблице «Пользователи» (PATCH branch).
        wh = User.objects.create_user("wh2", password="pass1234", role=User.Role.WAREHOUSE)
        r = self.client.patch(f"/api/users/{wh.id}/", {"branch": self.branch.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        wh.refresh_from_db()
        self.assertEqual(wh.branch_id, self.branch.id)


class PasswordPolicyTests(APITestCase):
    """Слабые/угадываемые пароли отклоняются API создания пользователя, чтобы их
    нельзя было перебрать снаружи (AUTH_PASSWORD_VALIDATORS через сериализатор)."""

    def setUp(self):
        self.admin = User.objects.create_user("admin_pw", password="pass1234", role=User.Role.ADMIN)
        self.client.force_authenticate(self.admin)

    def _create(self, password, username="newuser"):
        return self.client.post("/api/users/", {
            "username": username, "role": "MANAGER", "password": password,
        }, format="json")

    def test_short_password_rejected(self):
        r = self._create("ab12cd")           # 6 символов < 8
        self.assertEqual(r.status_code, 400)
        self.assertIn("password", r.data)

    def test_all_numeric_password_rejected(self):
        r = self._create("48213756")         # 8, но полностью числовой
        self.assertEqual(r.status_code, 400)
        self.assertIn("password", r.data)

    def test_common_password_rejected(self):
        r = self._create("password")         # из списка распространённых
        self.assertEqual(r.status_code, 400)
        self.assertIn("password", r.data)

    def test_password_similar_to_username_rejected(self):
        r = self._create("director1", username="director1")  # совпадает с логином
        self.assertEqual(r.status_code, 400)
        self.assertIn("password", r.data)

    def test_strong_password_accepted(self):
        r = self._create("Zx9!mfP2qL")
        self.assertEqual(r.status_code, 201, r.data)


class LoginThrottleTests(APITestCase):
    """Логин ограничен по частоте — защита от перебора паролей/credential stuffing."""

    def setUp(self):
        cache.clear()   # throttle state lives in the cache — isolate each test
        User.objects.create_user("brute", password="Zx9!mfP2qL", role=User.Role.MANAGER)

    def tearDown(self):
        cache.clear()

    def test_login_throttled_after_limit(self):
        # Неверные пароли всё равно считаются: после лимита попыток с одного IP — 429.
        codes = [
            self.client.post("/api/auth/login/", {"username": "brute", "password": "wrong"}, format="json").status_code
            for _ in range(_LOGIN_LIMIT + 1)
        ]
        self.assertEqual(codes.count(401), _LOGIN_LIMIT)  # лимит попыток исчерпан
        self.assertEqual(codes[-1], 429)                  # следующая — отбита

    def test_valid_login_returns_tokens(self):
        r = self.client.post("/api/auth/login/", {"username": "brute", "password": "Zx9!mfP2qL"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("access", r.data)
        self.assertIn("refresh", r.data)
