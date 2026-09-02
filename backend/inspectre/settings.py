from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-only-not-for-production")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# Trust the SPA nginx container's X-Forwarded-Proto header (frontend/proxy.conf
# sets it on every proxied request) so Django knows the original request was
# HTTPS even though it reaches gunicorn over plain HTTP inside the container
# network. Without this, request.is_secure() is always False behind the
# proxy, causing CSRF origin checks to fail for HTTPS deployments.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Comma-separated list of scheme+host origins allowed to submit CSRF-protected
# POSTs (e.g. https://inspectre.internal.dev.aws.zorgdomein.nl). Empty by
# default — same-origin local/docker-compose dev needs no entry.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

AWS_IAM_AUTH_ENABLED = env.bool("AWS_IAM_AUTH_ENABLED", default=False)
AWS_REGION = env("AWS_REGION", default="us-east-1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "storages",
    "core",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves /static/ under gunicorn (runserver-only handling
    # doesn't apply in production). Must come right after SecurityMiddleware.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "inspectre.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

WSGI_APPLICATION = "inspectre.wsgi.application"

if AWS_IAM_AUTH_ENABLED:
    DATABASES = {
        "default": {
            "ENGINE": "core.db_backends.iam_postgres",
            "NAME": env("DATABASE_NAME"),
            "USER": env("DATABASE_USER"),
            "HOST": env("DATABASE_HOST"),
            "PORT": env("DATABASE_PORT", default="5432"),
        }
    }
else:
    DATABASES = {"default": env.db("DATABASE_URL", default="postgres://inspectre:inspectre@db:5432/inspectre")}

STORAGES = {
    "default": {"BACKEND": "storages.backends.s3.S3Storage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
AWS_STORAGE_BUCKET_NAME = env("S3_BUCKET_NAME", default="inspectre-screenshots")
AWS_S3_REGION_NAME = env("S3_REGION", default="us-east-1")
AWS_S3_ENDPOINT_URL = env("S3_ENDPOINT_URL", default=None)
if not AWS_IAM_AUTH_ENABLED:
    AWS_ACCESS_KEY_ID = env("S3_ACCESS_KEY_ID", default="")
    AWS_SECRET_ACCESS_KEY = env("S3_SECRET_ACCESS_KEY", default="")
AWS_DEFAULT_ACL = None
# Browser-reachable origin for presigned URLs. Set S3_PUBLIC_BASE_URL in dev
# (e.g. http://localhost:9000/inspectre-screenshots) so presigning targets a
# host the browser can reach instead of the container-internal S3 endpoint.
# Omit in prod, where the real S3 endpoint is already browser-reachable.
_s3_public_base_url = env("S3_PUBLIC_BASE_URL", default=None)
if _s3_public_base_url:
    from urllib.parse import urlparse

    _parsed = urlparse(_s3_public_base_url)
    # Presigned URLs must be signed against a host the browser can reach.
    # This is S3_PUBLIC_BASE_URL's origin without the bucket path suffix,
    # since boto3's endpoint_url must not include the bucket itself.
    AWS_S3_PRESIGN_ENDPOINT_URL = f"{_parsed.scheme}://{_parsed.netloc}"
else:
    # No public base URL override (real S3 in prod): the internal endpoint
    # is already browser-reachable, so presigning uses the same endpoint.
    AWS_S3_PRESIGN_ENDPOINT_URL = AWS_S3_ENDPOINT_URL

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

LOGIN_URL = "/admin/login/"
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
}

IMAGE_DIFF_THRESHOLD = env.float("IMAGE_DIFF_THRESHOLD", default=0.1)
RUN_RETENTION_PER_SUITE = env.int("RUN_RETENTION_PER_SUITE", default=5)
DEFAULT_FUZZ_LEVEL = env("DEFAULT_FUZZ_LEVEL", default="30%")
DEFAULT_HIGHLIGHT_COLOUR = env("DEFAULT_HIGHLIGHT_COLOUR", default="ff0000")
THUMBNAIL_WIDTH = env.int("THUMBNAIL_WIDTH", default=300)
THUMBNAIL_JPEG_QUALITY = env.int("THUMBNAIL_JPEG_QUALITY", default=90)

ADMIN_USERNAME = env("ADMIN_USERNAME", default="admin")
ADMIN_PASSWORD = env("ADMIN_PASSWORD", default=None)

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

IMAGEMAGICK_TIMEOUT_SECONDS = env.int("IMAGEMAGICK_TIMEOUT_SECONDS", default=60)

if AWS_IAM_AUTH_ENABLED:
    _redis_host = env("REDIS_HOST")
    _redis_port = env.int("REDIS_PORT", default=6379)
    REDIS_IAM_USERNAME = env("REDIS_IAM_USERNAME")
    # The IAM auth token signs the cache name, while REDIS_HOST is the endpoint the
    # client connects to — for a replication group these differ (cache "my-cache" is
    # reached at "master.my-cache.<hash>.<region>.cache.amazonaws.com"). Required
    # rather than derived from the endpoint: a wrong guess fails as an opaque
    # WRONGPASS at connect time, whereas a missing value fails loudly at startup.
    REDIS_IAM_CACHE_NAME = env("REDIS_IAM_CACHE_NAME")
    REDIS_HOST = _redis_host
    CELERY_BROKER_URL = (
        f"rediss://{_redis_host}:{_redis_port}/0"
        "?credential_provider=core.cache_backends.iam_credential_provider.IAMElastiCacheCredentialProvider"
    )
else:
    CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = None
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_WORKER_CONCURRENCY = env.int("CELERY_WORKER_CONCURRENCY", default=2)
# Set to True in tests so tasks run synchronously without a broker.
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_EAGER_PROPAGATES = env.bool("CELERY_TASK_EAGER_PROPAGATES", default=False)
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.json.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
        },
        "plain": {
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json" if not DEBUG else "plain",
        },
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "core": {"level": "INFO", "propagate": True},
        "django": {"level": "WARNING", "propagate": True},
    },
}
