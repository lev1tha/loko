from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from accounts.views import LokoTokenObtainPairView, UserViewSet
from business.views import DebtViewSet, DepositViewSet
from express.views import SaleViewSet
from finance.views import (
    AccountViewSet,
    AppSettingsView,
    ExpenseViewSet,
    TransferViewSet,
    balances,
    breakdown_report,
    business_orders_report,
    cashflow_report,
    debts_report,
    journal_report,
    pnl_report,
)

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")
router.register("accounts", AccountViewSet, basename="account")
router.register("expenses", ExpenseViewSet, basename="expense")
router.register("transfers", TransferViewSet, basename="transfer")
router.register("sales", SaleViewSet, basename="sale")
router.register("deposits", DepositViewSet, basename="deposit")
router.register("debts", DebtViewSet, basename="debt")

api_urlpatterns = [
    # Auth (login is the only public endpoint)
    path("auth/login/", LokoTokenObtainPairView.as_view(), name="login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # Settings + reports
    path("settings/", AppSettingsView.as_view(), name="settings"),
    path("reports/pnl/", pnl_report, name="pnl"),
    path("reports/cashflow/", cashflow_report, name="cashflow"),
    path("reports/balances/", balances, name="balances"),
    path("reports/debts/", debts_report, name="debts"),
    path("reports/business-orders/", business_orders_report, name="business_orders"),
    path("reports/journal/", journal_report, name="journal"),
    path("reports/breakdown/", breakdown_report, name="breakdown"),
    # OpenAPI schema + interactive docs (Swagger / Redoc)
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api:schema"), name="swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="api:schema"), name="redoc"),
    # Router (CRUD resources)
    *router.urls,
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include((api_urlpatterns, "api"))),
]
