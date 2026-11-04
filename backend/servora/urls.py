from django.contrib import admin
from django.contrib.auth import views as auth_views

from apps.accounts.forms import PhoneOrEmailResetForm
from django.urls import include, path

from apps.superadmin import views as superadmin_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("superadmin/", include("apps.superadmin.urls")),
    path("setup/", superadmin_views.setup, name="setup"),
    path("healthz", superadmin_views.healthz),
    path("password-reset/", auth_views.PasswordResetView.as_view(form_class=PhoneOrEmailResetForm), name="password_reset"),
    path("password-reset/sent/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password-reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password-reset/done/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("api/", include("servora.api_urls")),
    path("", include("apps.web.urls")),
]
