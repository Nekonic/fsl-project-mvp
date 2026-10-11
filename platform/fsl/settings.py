import os
from pathlib import Path

from range import declared
from rules.suricata import RULE_PATH

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get("DJANGO_DEBUG", "") == "1"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "") or "insecure-lab-key"

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "api",
    "console",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "api.refusals.SameOriginOnly",
    "api.reachability.not_from_inside_the_range",
    "api.refusals.Refusals",
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

FSL_SUBSTRATE = os.environ.get("FSL_SUBSTRATE", "range.docker.Docker")
RANGE = declared.read(flavor=declared.flavor_for(FSL_SUBSTRATE))

ATTACKER_CONTAINER = RANGE.roles["attacker"]
ATTACKER_SOURCE_CONTAINER = RANGE.roles["proxy"]
ATTACKER_LABEL_FILE = "/label/active"
ATTACKER_ORIGIN_FILE = "/label/origin"
ATTACKER_TERMINAL_URL = "/vm-terminal/fsl-kali/"
ATTACKER_SESSION_TERMINAL_URL = (
    "/terminal/{session}/" if FSL_SUBSTRATE == "range.docker.Docker" else ""
)
WAF_TERMINAL_URL = "/vm-terminal/fsl-waf/"
WAF_SESSION_TERMINAL_URL = (
    "/waf-terminal/{session}/" if FSL_SUBSTRATE == "range.docker.Docker" else ""
)
SITE_PORT = 8002 if FSL_SUBSTRATE == "range.docker.Docker" else None
ATTACKER_ORIGIN_MODE = os.environ.get(
    "ATTACKER_ORIGIN_MODE", "snat" if "edge" in RANGE.roles else "host-rewrite"
)
ATTACKER_TARGET_URL = os.environ.get("ATTACKER_TARGET_URL", os.environ.get("PUBLIC_TARGET_URL", "http://board.com"))

TARGET_URL = os.environ.get("TARGET_URL", "http://board.com")
PUBLIC_TARGET_URL = os.environ.get("PUBLIC_TARGET_URL", "http://board.com")

BOARD_API_URL = os.environ.get("BOARD_API_URL", "http://board:8000")
WARGAME_CASES_DIR = os.environ.get(
    "WARGAME_CASES_DIR", str(BASE_DIR.parent / "redteam" / "cases")
)

ELASTIC_URL = os.environ.get("ELASTIC_URL", "http://elasticsearch:9200")
ELASTIC_INDEX = os.environ.get("ELASTIC_INDEX", "fsl-logs-*")
ELASTIC_SESSION_INDEX = os.environ.get(
    "ELASTIC_SESSION_INDEX",
    "fsl-logs-{session}-*" if FSL_SUBSTRATE == "range.docker.Docker" else "",
)

READY_SKEW = float(os.environ.get("FSL_READY_SKEW", "5"))
CANARY_WAIT = float(os.environ.get("FSL_CANARY_WAIT", "45"))
CANARY_POLL = float(os.environ.get("FSL_CANARY_POLL", "3"))
SENSOR_HOST = RANGE.hosts.get(RANGE.roles.get("sensor", ""))
FSL_SENSOR_RULES = (
    os.environ.get("FSL_SENSOR_RULES")
    or (SENSOR_HOST and SENSOR_HOST.rules)
    or RULE_PATH
)
FSL_SENSOR_RELOAD = tuple((
    os.environ.get("FSL_SENSOR_RELOAD")
    or (SENSOR_HOST and SENSOR_HOST.reload)
    or "suricatasc -c reload-rules"
).split())
FSL_SOURCE = os.environ.get("FSL_SOURCE", str(BASE_DIR.parent))

FSL_SUBSTRATE_OPTIONS = dict(
    {
        "range.docker.Docker": {
            "project": os.environ.get("FSL_PROJECT", "fsl"),
            "session_file": os.path.join(FSL_SOURCE, "session.yaml"),
            "max_sessions": int(os.environ.get("FSL_MAX_SESSIONS") or 2),
        },
        "range.openstack.connect": {
            name: os.environ.get(variable, "")
            for name, variable in {
                "keystone": "FSL_OPENSTACK_KEYSTONE",
                "user": "FSL_OPENSTACK_USER",
                "password": "FSL_OPENSTACK_PASSWORD",
                "domain": "FSL_OPENSTACK_DOMAIN",
                "project": "FSL_OPENSTACK_PROJECT",
                "ssh_user": "FSL_OPENSTACK_SSH_USER",
                "ssh_key": "FSL_OPENSTACK_SSH_KEY",
                "region": "FSL_OPENSTACK_REGION",
                "interface": "FSL_OPENSTACK_INTERFACE",
                "base_image": "FSL_OPENSTACK_BASE_IMAGE",
                "flavor": "FSL_OPENSTACK_FLAVOR",
                "build_flavor": "FSL_OPENSTACK_BUILD_FLAVOR",
                "role_flavors": "FSL_OPENSTACK_ROLE_FLAVORS",
                "availability_zone": "FSL_OPENSTACK_AVAILABILITY_ZONE",
                "subnets": "FSL_OPENSTACK_SUBNETS",
                "mtu": "FSL_OPENSTACK_MTU",
                "opnsense": "FSL_OPNSENSE",
                "build_network": "FSL_OPENSTACK_BUILD_NETWORK",
                "platform": "FSL_OPENSTACK_PLATFORM",
            }.items()
        } | {"source": FSL_SOURCE},
    }.get(FSL_SUBSTRATE, {}),
    declared=RANGE,
)
