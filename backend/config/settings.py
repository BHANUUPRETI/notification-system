"""
Django settings for the Notification System backend.

Everything environment-specific is read from environment variables (see
.env.example). The project is structured so that it runs locally with zero
credentials (sandbox mode) and on Render with real sandbox keys.
"""

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env from the backend/ folder if it exists.
load_dotenv(BASE_DIR / ".env")


# ---------------------------------------------------------------------------
# Small env helpers
# ---------------------------------------------------------------------------
def env_str(key: str, default: str = "") -> str:
    """Read an env var. A blank value is treated as unset so that an empty
    variable in a dashboard cannot silently disable a required setting."""
    value = os.getenv(key)
    if value is None:
        return default
    value = value.strip()
    return value or default


def env_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(key: str, default: int) -> int:
    try:
        return int(env_str(key, str(default)))
    except (TypeError, ValueError):
        return default


def env_list(key: str, default: str = "") -> list[str]:
    raw = os.getenv(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
DEV_SECRET_KEY = "django-insecure-dev-only-change-me"
SECRET_KEY = env_str("DJANGO_SECRET_KEY", DEV_SECRET_KEY)
DEBUG = env_bool("DJANGO_DEBUG", True)

if not DEBUG and SECRET_KEY == DEV_SECRET_KEY:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set to a long random value when DJANGO_DEBUG is "
        "False. Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
    )

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "*")

# Behind Render / Vercel proxies we need this so request.is_secure() is right.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "rest_framework",
    "rest_framework.authtoken",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    # local
    "notifications",
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
]

ROOT_URLCONF = "config.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# ---------------------------------------------------------------------------
# Database  (sqlite locally, postgres on Render)
# ---------------------------------------------------------------------------
if env_str("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env_str("POSTGRES_DB"),
            "USER": env_str("POSTGRES_USER"),
            "PASSWORD": env_str("POSTGRES_PASSWORD"),
            "HOST": env_str("POSTGRES_HOST"),
            "PORT": env_str("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": env_int("CONN_MAX_AGE", 60),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# We log in with username OR email, so both must be unique.
AUTHENTICATION_BACKENDS = ["notifications.backends.EmailOrUsernameBackend"]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
    "DEFAULT_PAGINATION": None,
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}


# ---------------------------------------------------------------------------
# CORS  (the Next.js app on Vercel calls this API)
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list("CORS_ORIGINS", "http://localhost:3000")
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env_list(
    "CORS_ORIGINS", "http://localhost:3000"
)  # Django 4+ requires this for cookie/session auth


# ---------------------------------------------------------------------------
# I18N / static
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# The hashed manifest only works once `collectstatic` has run, so keep the
# plain storage in DEBUG (where staticfiles/ usually does not exist yet).
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- security (only bite in production) ---
if not DEBUG:
    # Render/Vercel terminate TLS and forward X-Forwarded-Proto, so Django can
    # redirect plain HTTP without breaking the proxy hop.
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 60 * 60 * 24 * 7)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    SECURE_REFERRER_POLICY = "same-origin"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "[{levelname}] {asctime} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "notifications": {"level": env_str("LOG_LEVEL", "INFO"), "handlers": ["console"], "propagate": False},
    },
}


# ---------------------------------------------------------------------------
# Notification System
# ---------------------------------------------------------------------------
NOTIFICATIONS = {
    # When True nothing is sent over the network. Messages are rendered, stored
    # as NotificationLog rows with status=simulated, and printed to the console.
    # Flip to False once the sandbox keys below are filled in.
    "SANDBOX": env_bool("NOTIFICATION_SANDBOX", True),
    "DEFAULT_FROM_NAME": env_str("DEFAULT_FROM_NAME", "Notify Demo"),
    "DEFAULT_REPLY_TO": env_str("DEFAULT_REPLY_TO", "noreply@example.com"),
    "FRONTEND_URL": env_str("FRONTEND_URL", "http://localhost:3000"),
    "LOG_RETENTION_DAYS": env_int("LOG_RETENTION_DAYS", 90),
    # Shared secret for POST /api/internal/scan-inactive/ so the daily
    # inactivity scan can be triggered by an external scheduler on a free
    # Render plan (which cannot run cron jobs).
    "SCAN_TOKEN": env_str("SCAN_TOKEN"),
    "WHATSAPP": {
        "ACCESS_TOKEN": env_str("WHATSAPP_ACCESS_TOKEN"),
        "PHONE_NUMBER_ID": env_str("PHONE_NUMBER_ID"),
        "BUSINESS_ACCOUNT_ID": env_str("WHATSAPP_BUSINESS_ACCOUNT_ID"),
        "API_VERSION": env_str("WHATSAPP_API_VERSION", "v21.0"),
        "TEMPLATE_LANGUAGE": env_str("WHATSAPP_TEMPLATE_LANGUAGE", "en_US"),
        "TEST_RECIPIENTS": env_list("WHATSAPP_TEST_RECIPIENTS"),
    },
    "EMAIL": {
        "PROVIDER": env_str("EMAIL_PROVIDER", "postmark").lower(),
        "POSTMARK_TOKEN": env_str("POSTMARKAPP_TOKEN"),
        "POSTMARK_FROM_EMAIL": env_str("POSTMARK_FROM_EMAIL"),
        "BREVO_API_KEY": env_str("BREVO_API_KEY"),
        "BREVO_FROM_EMAIL": env_str("BREVO_FROM_EMAIL"),
        "RESEND_API_KEY": env_str("RESEND_API_KEY"),
        "RESEND_FROM_EMAIL": env_str("RESEND_FROM_EMAIL"),
        "MAILGUN_API_KEY": env_str("MAILGUN_API_KEY"),
        "MAILGUN_DOMAIN": env_str("MAILGUN_DOMAIN"),
        "MAILGUN_FROM_EMAIL": env_str("MAILGUN_FROM_EMAIL"),
        "AWS_ACCESS_KEY_ID": env_str("AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": env_str("AWS_SECRET_ACCESS_KEY"),
        "AWS_REGION": env_str("AWS_REGION", "us-east-1"),
        "SES_FROM_EMAIL": env_str("SES_FROM_EMAIL"),
    },
    "PUSH": {
        "ONESIGNAL_APP_ID": env_str("ONESIGNAL_APP_ID"),
        "ONESIGNAL_REST_API_KEY": env_str("ONESIGNAL_REST_API_KEY"),
        "VAPID_PUBLIC_KEY": env_str("VAPID_PUBLIC_KEY"),
        "VAPID_PRIVATE_KEY": env_str("VAPID_PRIVATE_KEY"),
        "VAPID_CLAIM_EMAIL": env_str("VAPID_CLAIM_EMAIL", "mailto:you@example.com"),
    },
}


# JWT is supported alongside the legacy DRF token during migration.
from datetime import timedelta
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}
