"""Django settings. Everything environment-specific is read from env vars with dev defaults."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def env_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes"}


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "fuel_route",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]
# Compresses the JSON (NYC→LA: 43.6 KB → 16.5 KB, 2.6x). Costs ~25% warm-path throughput in Python,
# so behind a proxy that compresses (nginx, CloudFront, ALB) set GZIP_RESPONSES=0 (ADR-0013).
if env_bool("GZIP_RESPONSES", True):
    MIDDLEWARE.insert(0, "django.middleware.gzip.GZipMiddleware")

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("SQLITE_PATH", BASE_DIR / "db.sqlite3"),
    }
}

# Route plans are deterministic for a (start, finish, fuel) triple, so cache them.
# Swap for Redis in production via CACHE_URL-style config.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "fuel-route",
        "TIMEOUT": 60 * 60 * 24,
    }
}
# Shared cache across workers and containers (docker-compose sets it). Keys are already
# namespaced by dataset version, so a shared cache stays correct across reloads (ADR-0007).
if REDIS_URL := os.environ.get("REDIS_URL"):
    CACHES["default"] = {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "TIMEOUT": 60 * 60 * 24,
        "KEY_PREFIX": "fuel-route",
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"
STATIC_URL = "static/"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "fuel_route.api.errors.exception_handler",
}

FUEL_ROUTE = {
    "VEHICLE_RANGE_MILES": 500,
    "VEHICLE_MPG": 10,
    # Max distance between a station and the route for it to count as "on the way".
    # Stations are geocoded to their city centroid, so this absorbs that imprecision.
    "CORRIDOR_MILES": float(os.environ.get("CORRIDOR_MILES", 10)),
    # Cost assigned to each extra stop when choosing where to refuel (time, overhead).
    # The plan only adds a stop when it saves more than this; 0 = pure cheapest fuel.
    "STOP_PENALTY_USD": float(os.environ.get("STOP_PENALTY_USD", 5)),
    "OSRM_URL": os.environ.get("OSRM_URL", "https://router.project-osrm.org"),
    "NOMINATIM_URL": os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org"),
    # Free-text addresses fall back to Nominatim; "City, ST" and "lat,lng" never do.
    "GEOCODER_FALLBACK": env_bool("GEOCODER_FALLBACK", True),
    "HTTP_TIMEOUT_SECONDS": 15,
    # Routes, geocodes and plans are deterministic for the same inputs and price file.
    "CACHE_TTL_SECONDS": int(os.environ.get("CACHE_TTL_SECONDS", 60 * 60 * 24)),
    # How long a worker trusts its last read of the dataset version (max staleness after a reload).
    "DATASET_VERSION_TTL_SECONDS": float(os.environ.get("DATASET_VERSION_TTL_SECONDS", 1.0)),
    "USER_AGENT": "spotter-fuel-route/0.1",
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "loggers": {"fuel_route": {"handlers": ["console"], "level": "INFO"}},
}
