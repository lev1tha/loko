from django.urls import path

from . import kargo_views as v

urlpatterns = [
    path("auth/login/", v.login, name="kargo-login"),
    path("auth/register/", v.register, name="kargo-register"),
    path("auth/change-password/", v.change_password, name="kargo-change-password"),
    path("auth/recovery/", v.recovery, name="kargo-recovery"),
    path("auth/reset-password/", v.reset_password, name="kargo-reset-password"),
    path("clients/<int:pk>/", v.client_detail, name="kargo-client"),
    path("clients/<int:pk>/orders/", v.client_orders, name="kargo-client-orders"),
    path("track/", v.track, name="kargo-track"),
    path("branches/", v.branches, name="kargo-branches"),
    path("orders/shipments/", v.shipments, name="kargo-shipments"),
    path("orders/arrive/", v.arrive, name="kargo-arrive"),
    path("orders/pickup/", v.pickup, name="kargo-pickup"),
    path("sync/", v.sync_status, name="kargo-sync"),
]
