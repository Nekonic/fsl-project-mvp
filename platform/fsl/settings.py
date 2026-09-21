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
# Not the same container: the terminal's traffic is proxied, so this is who
# the WAF and the IDS see.
ATTACKER_SOURCE_CONTAINER = os.environ.get("ATTACKER_SOURCE_CONTAINER", "fsl-proxy")
ATTACKER_LABEL_FILE = os.environ.get("ATTACKER_LABEL_FILE", "/label/active")
ATTACKER_ORIGIN_FILE = os.environ.get("ATTACKER_ORIGIN_FILE", "/label/origin")
ATTACKER_NETWORK = os.environ.get("ATTACKER_NETWORK", "fsl_edge")
ATTACKER_TERMINAL_URL = os.environ.get("ATTACKER_TERMINAL_URL", "http://localhost:7681")

# Where the red team's traffic goes, and where its case files live. Inside the
# stack the attacks leave this container, so the target is the WAF by service
# name; on a developer's host it is the published port.
TARGET_URL = os.environ.get("TARGET_URL", "http://localhost:8080")
# The name the target answers to, which is what an attacker dials. TARGET_URL
# names a segment so the platform can choose which address to attack from;
# that is routing, and it is not what the site is called.
PUBLIC_TARGET_URL = os.environ.get("PUBLIC_TARGET_URL", "http://shop.com")

# The inside. The wiki records what was read of it, which is how it judges its
# own defeat - the same rule the shop follows with its `solved` flag.
WIKI_READ_LOG = os.environ.get("WIKI_READ_LOG", "/wiki-logs/read.log")
WIKI_SECRET_PATH = os.environ.get("WIKI_SECRET_PATH", "/runbooks/deploy.html")
TOOL_TARGET_URL = os.environ.get("TOOL_TARGET_URL", "http://waf:8080")
# The target's own API, reached directly and never through the WAF: polling it
# through the proxy would put the range's own housekeeping into the alert
# stream, where it could be scored as a false positive against the defence.
WARGAME_API_URL = os.environ.get("WARGAME_API_URL", "http://juice-shop:3000")
# How long to let the target settle before asking what a case took. It records
# a solve after answering the request that earned it, and the red team blocks
# on this response, so this is what keeps consecutive cases far enough apart to
# tell apart. Unit tests mock the target and set it to zero.
TARGET_SETTLE = float(os.environ.get("TARGET_SETTLE", "0.25"))
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
