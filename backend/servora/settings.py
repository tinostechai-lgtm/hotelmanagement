"""
Servora — Restaurant & Hotel F&B SaaS platform.

Settings read from environment variables so the same code runs locally
(SQLite) and on Vercel (Postgres via DATABASE_URL).
"""
import os
from datetime import timedelta
from pathlib import Path

import warnings

import dj_database_url

warnings.filterwarnings("ignore", message="No directory at")

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-change-me-servora-local-only-key-0123456789")
DEBUG = env_bool("DJANGO_DEBUG", not os.environ.get("VERCEL"))
if os.environ.get("DATABASE_URL") and not DEBUG and "DJANGO_SECRET_KEY" not in os.environ:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY before running Servora with a real database.")
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", ".vercel.app,localhost,127.0.0.1,testserver").split(",")
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "https://*.vercel.app").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "rest_framework",
    "corsheaders",
    "apps.tenants",
    "apps.accounts",
    "apps.subscriptions",
    "apps.menu",
    "apps.operations",
    "apps.delivery",
    "apps.inventory",
    "apps.crm",
    "apps.hardware",
    "apps.web",
    "apps.superadmin",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.tenants.middleware.TenantMiddleware",
]

ROOT_URLCONF = "servora.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.tenants.context_processors.tenant",
            ],
        },
    },
]

WSGI_APPLICATION = "servora.wsgi.application"

# Production: set DATABASE_URL (Vercel Postgres / Neon / Supabase). Vercel's
# filesystem is read-only, so SQLite there falls back to /tmp (demo only).
_sqlite = "/tmp/servora.sqlite3" if os.environ.get("VERCEL") else BASE_DIR / "db.sqlite3"
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{_sqlite}",
        conn_max_age=int(os.environ.get("DB_CONN_MAX_AGE", "60")),
    )
}

AUTH_USER_MODEL = "accounts.User"
# One login field: mobile number or email.
AUTHENTICATION_BACKENDS = ["apps.accounts.backends.EmailOrPhoneBackend", "django.contrib.auth.backends.ModelBackend"]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]
LOGIN_URL = "web:login"
LOGIN_REDIRECT_URL = "web:dashboard"
LOGOUT_REDIRECT_URL = "web:home"

LANGUAGE_CODE = "en-in"
TIME_ZONE = os.environ.get("TIME_ZONE", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}
# Serve static files straight from the source folders (no collectstatic step on Vercel).
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 100,
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle", "rest_framework.throttling.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": "120/min", "user": "1200/min", "login": "10/min"},
}
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=12),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
}

CORS_ALLOW_ALL_ORIGINS = env_bool("CORS_ALLOW_ALL", True)
CORS_ALLOW_HEADERS = ["*", "authorization", "content-type", "x-restaurant", "x-device-key"]

# Email uses the SMTP settings saved in Super admin → Platform settings → Email.
EMAIL_BACKEND = "apps.superadmin.email_backend.PlatformEmailBackend"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Servora <no-reply@servora.app>")

# Razorpay — normally set in Super admin → Platform settings; env vars are a fallback.
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")

# Optional integrations
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
AGGREGATOR_WEBHOOK_SECRET = os.environ.get("AGGREGATOR_WEBHOOK_SECRET", "")

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
# Signed-cookie sessions: logins work on every serverless instance and need no
# session table. (Cookies are signed with SECRET_KEY and are HttpOnly.)
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
# True on Vercel without DATABASE_URL: data lives in per-instance /tmp SQLite.
DEMO_MODE = bool(os.environ.get("VERCEL")) and not os.environ.get("DATABASE_URL")
# Latest Android APK (published by .github/workflows/android.yml). Overridable in Super admin → General.
ANDROID_APK_URL = os.environ.get("ANDROID_APK_URL", "https://github.com/tinostechai-lgtm/hotelmanagement/releases/latest/download/servora.apk")
# Online order tabs left unpaid at Razorpay are auto-cancelled after this many minutes.
UNPAID_ONLINE_ORDER_TTL_MINUTES = int(os.environ.get("UNPAID_ONLINE_ORDER_TTL_MINUTES", "20"))

LOGGING = {
    "version": 1,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
