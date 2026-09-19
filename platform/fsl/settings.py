import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "insecure-mvp-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "api",
    "console",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "fsl.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DJANGO_DB_PATH", BASE_DIR / "db.sqlite3"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"
STATIC_URL = "static/"

# The attacker's box, for free-form traffic typed in the terminal.
ATTACKER_CONTAINER = os.environ.get("ATTACKER_CONTAINER", "fsl-kali")
ATTACKER_NETWORK = os.environ.get("ATTACKER_NETWORK", "fsl_fsl")
ATTACKER_TERMINAL_URL = os.environ.get("ATTACKER_TERMINAL_URL", "http://localhost:7681")

# Where the red team's traffic goes, and where its case files live. Inside the
# stack the attacks leave this container, so the target is the WAF by service
# name; on a developer's host it is the published port.
TARGET_URL = os.environ.get("TARGET_URL", "http://localhost:8080")
TOOL_TARGET_URL = os.environ.get("TOOL_TARGET_URL", "http://waf:8080")
WARGAME_CASES_DIR = os.environ.get(
    "WARGAME_CASES_DIR", str(BASE_DIR.parent / "redteam" / "cases")
)

# Where this process meets the stack. All env vars, so tests run outside Docker.
ELASTIC_URL = os.environ.get("ELASTIC_URL", "http://elasticsearch:9200")
ELASTIC_INDEX = os.environ.get("ELASTIC_INDEX", "fsl-logs-*")
SURICATA_CONTAINER = os.environ.get("SURICATA_CONTAINER", "fsl-suricata")
SURICATA_RULE_PATH = os.environ.get("SURICATA_RULE_PATH", "/rules/local.rules")
SURICATA_CANDIDATE_PATH = os.environ.get(
    "SURICATA_CANDIDATE_PATH", "/rules/candidate.rules"
)
SURICATA_RULE_PATH_IN_IDS = os.environ.get(
    "SURICATA_RULE_PATH_IN_IDS", "/var/lib/suricata/rules/local.rules"
)
SURICATA_CANDIDATE_PATH_IN_IDS = os.environ.get(
    "SURICATA_CANDIDATE_PATH_IN_IDS", "/var/lib/suricata/rules/candidate.rules"
)
