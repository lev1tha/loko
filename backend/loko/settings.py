"""
Django settings for the Loko ERP project.

First module: Loko Express (cargo delivery China -> Kyrgyzstan).
Designed to be modular so the future "Loko Business" direction can be
plugged in as additional apps without touching the existing ones.
"""

from datetime import timedelta
from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config(
    "SECRET_KEY",
    default="django-insecure-d7pf@(-@0(@m8p06q#+&ed94-_d4j1*#c(oresqf$u*1jgzm$1",
)

DEBUG = config("DEBUG", default=True, cast=bool)

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="*", cast=Csv())

# Behind a TLS-terminating reverse proxy (Cloudflare Tunnel or host nginx) the
# app speaks HTTP locally but is HTTPS publicly.
USE_CLOUDFLARE = config("USE_CLOUDFLARE", default=not DEBUG, cast=bool)

# Fail closed in production: never boot with the public, insecure dev SECRET_KEY.
if not DEBUG and (not SECRET_KEY or SECRET_KEY.startswith("django-insecure-")):
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "SECRET_KEY must be a strong secret when DEBUG=False. "
        'Generate one: python -c "import secrets; print(secrets.token_urlsafe(64))"'
    )


# Application definition

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_spectacular",
    "corsheaders",
]

LOCAL_APPS = [
    "accounts",
    "finance",
    "express",
    "business",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves Django admin/static files in production (no extra server).
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "loko.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "loko.wsgi.application"


# Database — SQLite by default; PostgreSQL in production via env vars.
if config("POSTGRES_DB", default=""):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("POSTGRES_DB"),
            "USER": config("POSTGRES_USER", default="postgres"),
            "PASSWORD": config("POSTGRES_PASSWORD", default=""),
            "HOST": config("POSTGRES_HOST", default="127.0.0.1"),
            "PORT": config("POSTGRES_PORT", default="5432"),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# Custom user model with role-based access (Admin / Manager-Cashier)
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]


# Internationalization
LANGUAGE_CODE = "ru"
TIME_ZONE = "Asia/Bishkek"
USE_I18N = True
USE_TZ = True


# Static files (served by WhiteNoise in production)
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Storage: media files → Cloudflare R2 (S3-compatible) when configured,
# else local filesystem in dev. Static always via WhiteNoise.
# ---------------------------------------------------------------------------
R2_BUCKET = config("R2_BUCKET", default="")
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
if R2_BUCKET:
    INSTALLED_APPS += ["storages"]
    STORAGES["default"] = {"BACKEND": "storages.backends.s3.S3Storage"}
    AWS_STORAGE_BUCKET_NAME = R2_BUCKET
    AWS_ACCESS_KEY_ID = config("R2_ACCESS_KEY_ID", default="")
    AWS_SECRET_ACCESS_KEY = config("R2_SECRET_ACCESS_KEY", default="")
    # R2 endpoint: https://<ACCOUNT_ID>.r2.cloudflarestorage.com
    AWS_S3_ENDPOINT_URL = config("R2_ENDPOINT_URL", default="")
    AWS_S3_REGION_NAME = "auto"
    AWS_S3_SIGNATURE_VERSION = "s3v4"
    AWS_S3_ADDRESSING_STYLE = "virtual"
    AWS_DEFAULT_ACL = None              # R2 doesn't support ACLs
    AWS_QUERYSTRING_AUTH = False        # public-read media via custom domain
    AWS_S3_FILE_OVERWRITE = False
    # Public CDN domain for media, e.g. media.loko.kg (R2 → custom domain)
    AWS_S3_CUSTOM_DOMAIN = config("R2_PUBLIC_DOMAIN", default="") or None
    MEDIA_URL = (
        f"https://{AWS_S3_CUSTOM_DOMAIN}/" if AWS_S3_CUSTOM_DOMAIN else f"{AWS_S3_ENDPOINT_URL}/{R2_BUCKET}/"
    )
else:
    STORAGES["default"] = {"BACKEND": "django.core.files.storage.FileSystemStorage"}
    MEDIA_URL = "media/"
    MEDIA_ROOT = BASE_DIR / "media"


# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PAGINATION_CLASS": "loko.pagination.StandardPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}


# drf-spectacular — OpenAPI 3 schema + Swagger/Redoc UI (/api/schema/, /api/docs/).
SPECTACULAR_SETTINGS = {
    "TITLE": "Loko ERP API",
    "DESCRIPTION": (
        "API ERP-системы Loko (Express + Business): продажи, расходы, переводы, "
        "депозиты, задолженности и отчёты ОПиУ/ОДДС."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Schema + Swagger/Redoc are NOT public — they expose the whole API surface.
    # Operators («Сотрудник») are blocked too: the schema would reveal every
    # finance/report endpoint they must not even know exists.
    "SERVE_PERMISSIONS": ["accounts.permissions.DenyOperator"],
    # No SERVERS entry: paths already carry the /api prefix (urlconf include),
    # so adding url:/api would double-prefix Swagger "Try it out" → /api/api/…
    "COMPONENT_SPLIT_REQUEST": True,
    # Несколько enum-ов с полем «module» сталкиваются по имени: finance.Module
    # (3 значения, у счетов), направление директора (2 значения, с метками) и
    # enum параметра ?module= в отчётах (2 значения, без меток). Даём каждому
    # стабильное имя — иначе spectacular ругается на коллизию (Module404Enum).
    # Хэш учитывает (value, label), поэтому ссылаемся на сами классы Choices.
    "ENUM_NAME_OVERRIDES": {
        "ModuleEnum": "finance.models.Module",
        "DirectorDirectionEnum": "accounts.models.User.Direction",
        "ModuleParamEnum": ["EXPRESS", "BUSINESS"],
    },
}


# SimpleJWT
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=8),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
}


# CORS — allow the Vite dev server (and the Cloudflare Pages domain in prod)
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174",
    cast=Csv(),
)
CORS_ALLOW_CREDENTIALS = True

# CSRF: trust the public frontend + API origins (needed for Django admin over HTTPS).
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="http://localhost:5173,http://localhost:5174",
    cast=Csv(),
)

# ---------------------------------------------------------------------------
# Production hardening — active behind Cloudflare (HTTPS terminated by CF).
# ---------------------------------------------------------------------------
if USE_CLOUDFLARE:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=False, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=0, cast=int)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    # Cloudflare passes the real client IP in this header (for rate limiting / logs).
    # (read via request.META["HTTP_CF_CONNECTING_IP"])


# ---------------------------------------------------------------------------
# Loko Express business defaults (overridable via the Settings model / admin)
# ---------------------------------------------------------------------------
LOKO_EXPRESS = {
    "PRICE_PER_KG_USD": "3",        # base client price: 3$ per kg
    "USD_RATE_SOM": "90",           # fixed internal rate: 1$ = 90 som
    "BASE_COST_PER_KG_SOM": "150",  # base (dynamic) cost price per kg
}
