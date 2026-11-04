from django.urls import path

from . import views

app_name = "superadmin"
urlpatterns = [
    path("", views.overview, name="overview"),
    path("restaurants/", views.restaurants, name="restaurants"),
    path("restaurants/<int:pk>/", views.restaurant_detail, name="restaurant"),
    path("plans/", views.plans, name="plans"),
    path("plans/new/", views.plan_edit, name="plan_new"),
    path("plans/<int:pk>/", views.plan_edit, name="plan_edit"),
    path("payments/", views.payments, name="payments"),
    path("users/", views.users, name="users"),
    path("settings/", views.settings_view, name="settings_home"),
    path("settings/<str:section>/", views.settings_view, name="settings"),
    path("test/<str:kind>/", views.settings_test, name="test"),
]
