from django.urls import path

from . import views

app_name = "web"
urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.login_view, name="login"),
    path("signup/", views.signup_view, name="signup"),
    path("logout/", views.logout_view, name="logout"),
    path("switch/", views.switch_restaurant, name="switch"),
    path("app/", views.dashboard, name="dashboard"),
    path("app/pos/", views.pos, name="pos"),
    path("app/orders/", views.orders, name="orders"),
    path("app/orders/<int:pk>/", views.orders, name="order_detail"),
    path("app/kitchen/", views.kitchen, name="kitchen"),
    path("app/delivery/", views.delivery, name="delivery"),
    path("app/menu/", views.menu, name="menu"),
    path("app/floor/", views.floor, name="floor"),
    path("app/tables/", views.floor),
    path("app/customers/", views.customers, name="customers"),
    path("app/inventory/", views.inventory, name="inventory"),
    path("app/reports/", views.reports, name="reports"),
    path("app/staff/", views.staff, name="staff"),
    path("app/hardware/", views.hardware, name="hardware"),
    path("app/settings/", views.settings_page, name="settings"),
    path("app/billing/", views.billing, name="billing"),
    path("app/qr-codes/", views.qr_sheet, name="qr_sheet"),
    path("s/<slug:slug>/", views.store, name="store"),
    path("t/<str:token>/", views.track, name="track"),
]
