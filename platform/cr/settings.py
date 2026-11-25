import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CR_SOURCE = Path(os.environ.get("CR_SOURCE") or BASE_DIR.parent)
CR_PROBES_OUT = Path(os.environ.get("CR_PROBES_OUT") or CR_SOURCE / "wargames")
ALLOCATION_IDLE_MINUTES = int(os.environ.get("CR_ALLOCATION_IDLE_MINUTES") or 30)
RETAIN_CLOSED_MINUTES = int(os.environ.get("CR_RETAIN_CLOSED_MINUTES") or 60)
READ_EVERY_SECONDS = float(os.environ.get("CR_READ_EVERY_SECONDS") or 5)
JUDGE_AFTER_SECONDS = float(os.environ.get("CR_JUDGE_AFTER_SECONDS") or 30)
REBUILD_EVERY_SECONDS = float(os.environ.get("CR_REBUILD_EVERY_SECONDS") or 5)
RETAIN_RECORDS_DAYS = int(os.environ.get("CR_RETAIN_RECORDS_DAYS") or 90)
BOT_ROUND_USERS = frozenset(name.strip() for name in os.environ.get("CR_BOT_ROUND_USERS", "").split(",") if name.strip())
BOT_LAUNCHER_KEY = os.environ.get("CR_BOT_LAUNCHER_KEY", "")
BOT_LAUNCHER_KEY_FILE = Path(os.environ.get("CR_BOT_LAUNCHER_KEY_FILE") or "/run/secrets/bots_launcher_key")

DEBUG = os.environ.get("DJANGO_DEBUG", "") == "1"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "") or "insecure-lab-key"

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "rest_framework",
    "drf_spectacular",
    "users",
    "sandbox",
    "telemetry",
    "training",
    "scoring",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "cr.urls"
APPEND_SLASH = False

SESSION_COOKIE_NAME = "cr_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_NAME = "cr_csrf"
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_FAILURE_VIEW = "cr.handler.csrf_refused"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": f"django.contrib.auth.password_validation.{name}"}
    for name in (
        "UserAttributeSimilarityValidator", "MinimumLengthValidator",
        "CommonPasswordValidator", "NumericPasswordValidator",
    )
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

DB_HOST = os.environ.get("CR_DB_HOST", "").strip()
DB_PASSWORD_FILE = Path(os.environ.get("CR_DB_PASSWORD_FILE") or "/run/secrets/store_password")


def store_password() -> str:
    given = os.environ.get("CR_DB_PASSWORD", "")
    if given or not DB_PASSWORD_FILE.is_file():
        return given
    return DB_PASSWORD_FILE.read_text().strip()


if DB_HOST:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": DB_HOST,
            "PORT": os.environ.get("CR_DB_PORT") or "5432",
            "NAME": os.environ.get("CR_DB_NAME") or "cr",
            "USER": os.environ.get("CR_DB_USER") or "cr",
            "PASSWORD": store_password(),
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get("DJANGO_DB_PATH", BASE_DIR / "db.sqlite3"),
            "OPTIONS": {"timeout": 30, "transaction_mode": "IMMEDIATE",
                        "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL"},
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "ko"
USE_TZ = True
TIME_ZONE = "UTC"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["users.permissions.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "cr.handler.handle",
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Cyber range",
    "VERSION": "1",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "POSTPROCESSING_HOOKS": ["drf_spectacular.hooks.postprocess_schema_enums", "cr.schema.error_shape"],
    "ENUM_NAME_OVERRIDES": {"ProblemKindEnum": "training.models.PROBLEM_KINDS",
                            "ProblemSideEnum": "training.models.PROBLEM_SIDES",
                            "VerdictEnum": "training.defence.serializers.VERDICTS",
                            "MatchupEnum": "training.models.MATCHUPS",
                            "PlayerSideEnum": "training.models.PLAYER_SIDES", "RoundPhaseEnum": "training.models.PHASES",
                            "BotRunStatusEnum": "training.models.RUN_STATES",
                            "BaselineStatusEnum": "training.models.BASELINE_STATES"},
}
