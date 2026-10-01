"""Настройки портала ИТ-отдела (PLAN-001, раздел «Окружение целиком»).

Все параметры установки и все секреты читаются из окружения (django-environ);
значений секретов в файле нет. Список переменных — deploy/.env.example.
"""
from pathlib import Path
from urllib.parse import urlsplit

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()

# --- Секреты и ключи (только из окружения) ---------------------------------

SECRET_KEY = env("DJANGO_SECRET_KEY")
# Ключи Fernet через запятую: первый шифрует, остальные только расшифровывают
# (MultiFernet; смена ключа — команда rotate_field_keys).
FIELD_ENCRYPTION_KEYS = env.list("FIELD_ENCRYPTION_KEYS")
if not FIELD_ENCRYPTION_KEYS:
    raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS: нужен хотя бы один ключ Fernet")
BACKUP_CODE_PEPPER = env("BACKUP_CODE_PEPPER")

DEBUG = False

# --- Адрес портала: из него выводятся ALLOWED_HOSTS и CSRF_TRUSTED_ORIGINS ---

PORTAL_URL = env("PORTAL_URL").rstrip("/")
_портал = urlsplit(PORTAL_URL)
if _портал.scheme not in ("http", "https") or not _портал.hostname:
    raise ImproperlyConfigured("PORTAL_URL: ожидается адрес вида https://хост[:порт]")
ALLOWED_HOSTS = [_портал.hostname]
CSRF_TRUSTED_ORIGINS = [f"{_портал.scheme}://{_портал.netloc}"]

# Адреса прокси администратора: настоящий адрес клиента берёт nginx
# (set_real_ip_from), Django его не пересчитывает.
TRUSTED_PROXIES = env.list("TRUSTED_PROXIES", default=[])

# --- Приложения -------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "django_otp",
    "django_rq",
    "apps.core",
    "apps.integrations.mail",
]
# Встроенной админки Django нет: администрирование — свой раздел с проверкой
# прав и журналом (PLAN-001, «Решения плана»).

# Миграции django_rq читают справочник типов из алиаса default (crm_app), а схему создаёт
# crm_owner (алиас migrate): на пустой базе они падают. У приложения только неуправляемые
# модели (панель админки, которой у нас нет), таблиц оно не создаёт.
MIGRATION_MODULES = {"django_rq": None}

AUTH_USER_MODEL = "core.User"
LOGIN_URL = "/login/"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.ClientIPMiddleware",
    "apps.core.middleware.ResponseHeadersMiddleware",
    "csp.middleware.CSPMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.SessionGuardMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
CSRF_FAILURE_VIEW = "apps.core.views.pages.csrf_failure"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "apps.core.context.shell",
            ],
        },
    },
]

# --- База данных -------------------------------------------------------------
# default — роль crm_app (web и worker). migrate — роль crm_owner, только для
# миграций: `python manage.py migrate --database=migrate`. В тестах схему
# создаёт crm_owner, а запросы идут под crm_app (backend/tests/conftest.py).

DATABASES = {"default": env.db("DATABASE_URL")}
if env("DATABASE_MIGRATE_URL", default=""):
    DATABASES["migrate"] = env.db("DATABASE_MIGRATE_URL")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Valkey: кэш и очереди RQ -------------------------------------------------

VALKEY_URL = env("VALKEY_URL")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": VALKEY_URL,
    },
}
RQ_QUEUES = {
    "mail": {"URL": VALKEY_URL, "DEFAULT_TIMEOUT": 120},
}

# --- Сессии в базе (закрывать по одной), пароли argon2 -----------------------

SESSION_ENGINE = "django.contrib.sessions.backends.db"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.Argon2PasswordHasher"]

# --- Язык и время -------------------------------------------------------------

LANGUAGE_CODE = "ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

# --- Защита (за прокси администратора TLS кончается на нём) -------------------

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_HSTS_SECONDS = 31536000
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# CSP без unsafe-inline и unsafe-eval: статика только своя (static/vendor/),
# Alpine — CSP-сборка, скрипты страниц — внешние файлы.
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": ["'self'"],
        "style-src": ["'self'"],
        "img-src": ["'self'", "data:"],
        "font-src": ["'self'"],
        "connect-src": ["'self'"],
        "object-src": ["'none'"],
        "base-uri": ["'self'"],
        "form-action": ["'self'"],
        "frame-ancestors": ["'none'"],
    },
}

# --- Статика и загрузки -------------------------------------------------------

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR.parent / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR.parent / "media"

# --- Исходящая почта (Mailpit на стенде, SMTP общества на установке) ----------

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("SMTP_HOST")
EMAIL_PORT = env.int("SMTP_PORT")
EMAIL_HOST_USER = env("SMTP_USER", default="")
EMAIL_HOST_PASSWORD = env("SMTP_PASSWORD", default="")
DEFAULT_FROM_EMAIL = env("SMTP_FROM")
_защита_smtp = env("SMTP_SECURITY", default="none")
if _защита_smtp not in ("starttls", "ssl", "none"):
    raise ImproperlyConfigured("SMTP_SECURITY: допустимо starttls, ssl или none")
EMAIL_USE_TLS = _защита_smtp == "starttls"
EMAIL_USE_SSL = _защита_smtp == "ssl"
EMAIL_TIMEOUT = 30
