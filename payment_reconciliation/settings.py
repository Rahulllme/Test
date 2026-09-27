"""Django settings for the order service."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def getenv(key, fallback):
    return os.environ.get(key) or fallback


SECRET_KEY = getenv("DJANGO_SECRET_KEY", "django-insecure-local-development-only")
DEBUG = getenv("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "orders.apps.OrdersConfig",
]

# A JSON API only: no sessions, no CSRF, no slash redirects.
MIDDLEWARE = [
    "orders.middleware.JSONErrorMiddleware",
]
APPEND_SLASH = False

ROOT_URLCONF = "payment_reconciliation.urls"
WSGI_APPLICATION = "payment_reconciliation.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": getenv("DB_HOST", "localhost"),
        "PORT": getenv("DB_PORT", "5432"),
        "USER": getenv("DB_USER", "postgres"),
        "PASSWORD": getenv("DB_PASSWORD", "postgres"),
        "NAME": getenv("DB_NAME", "orders"),
    }
}

TIME_ZONE = "UTC"
USE_TZ = True
USE_I18N = False
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

PAYLINK_BASE_URL = getenv("PAYLINK_BASE_URL", "http://127.0.0.1:9900")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
