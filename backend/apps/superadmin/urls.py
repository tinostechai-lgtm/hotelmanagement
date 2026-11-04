from django.urls import path

from . import views

app_name = "superadmin"
urlpatterns = [
    path("", views.overview, name="overview"),
    path("restaurants/", views.restaurants, name="restaurants"),
    path("restaurants/new/", views.add_client, name="add_client"),
    path("restaurants/<int:pk>/", views.restaurant_detail, name="restaurant"),
    path("team/", views.team, name="team"),
    path("team/roles/new/", views.role_edit, name="role_new"),
    path("team/roles/<int:pk>/", views.role_edit, name="role_edit"),
    path("activity/", views.activity, name="activity"),
    path("plans/", views.plans, name="plans"),
    path("plans/new/", views.plan_edit, name="plan_new"),
    path("plans/<int:pk>/", views.plan_edit, name="plan_edit"),
    path("payments/", views.payments, name="payments"),
    path("users/", views.users, name="users"),
    path("settings/", views.settings_view, name="settings_home"),
    path("settings/<str:section>/", views.settings_view, name="settings"),
    path("test/<str:kind>/", views.settings_test, name="test"),
]
