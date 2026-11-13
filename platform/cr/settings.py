import os
from pathlib import Path

from range import declared
from rules import crs
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

ROOT_URLCONF = "cr.urls"

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
        "OPTIONS": {"timeout": 30, "transaction_mode": "IMMEDIATE"},
    }
}

RESET_OWED_DIR = os.environ.get("CR_RESET_OWED_DIR", str(BASE_DIR / "reset-owed"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"
STATIC_URL = "static/"

CR_SUBSTRATE = os.environ.get("CR_SUBSTRATE", "range.openstack.connect")
RANGE = declared.read()

ATTACKER_CONTAINER = RANGE.roles["attacker"]
ATTACKER_SOURCE_CONTAINER = RANGE.roles["proxy"]
ATTACKER_LABEL_FILE = "/var/lib/session/active"
ATTACKER_TERMINAL_URL = "/vm-terminal/kali/"
ATTACKER_SESSION_TERMINAL_URL = "/vm-terminal/kali/?arg={session}"
WAF_TERMINAL_URL = "/vm-terminal/waf/"
WAF_SESSION_TERMINAL_URL = "/vm-terminal/waf/?arg={session}"
SITE_PORT = 8002
ATTACKER_TARGET_URL = os.environ.get("ATTACKER_TARGET_URL", os.environ.get("PUBLIC_TARGET_URL", "http://board.com"))

TARGET_URL = os.environ.get("TARGET_URL", "http://board.com")
PUBLIC_TARGET_URL = os.environ.get("PUBLIC_TARGET_URL", "http://board.com")

BOARD_API_URL = os.environ.get("BOARD_API_URL", "http://board:8000")
WARGAME_CASES_DIR = os.environ.get(
    "WARGAME_CASES_DIR", str(BASE_DIR.parent / "redteam" / "cases")
)

ELASTIC_URL = os.environ.get("ELASTIC_URL", "http://elasticsearch:9200")
ELASTIC_INDEX = os.environ.get("ELASTIC_INDEX", "logs-*")
ELASTIC_SESSION_INDEX = os.environ.get(
    "ELASTIC_SESSION_INDEX",
    {"range.openstack.connect": "logs-{slot}-*"}.get(CR_SUBSTRATE, ""),
)

READY_SKEW = float(os.environ.get("CR_READY_SKEW", "5"))
CANARY_WAIT = float(os.environ.get("CR_CANARY_WAIT", "45"))
CANARY_POLL = float(os.environ.get("CR_CANARY_POLL", "3"))
SCENARIO_TICK = float(os.environ.get("CR_SCENARIO_TICK", "2"))
SCENARIO_OBSERVE = float(os.environ.get("CR_SCENARIO_OBSERVE", "15"))
SCENARIO_WAF_POLL = float(os.environ.get("CR_SCENARIO_WAF_POLL", "20"))
RETAIN_CLOSED_MINUTES = int(os.environ.get("CR_RETAIN_CLOSED_MINUTES") or 60)
SENSOR_HOST = RANGE.hosts.get(RANGE.roles.get("sensor", ""))
CR_SENSOR_RULES = (
    os.environ.get("CR_SENSOR_RULES")
    or (SENSOR_HOST and SENSOR_HOST.rules)
    or RULE_PATH
)
CR_SENSOR_RELOAD = tuple((
    os.environ.get("CR_SENSOR_RELOAD")
    or (SENSOR_HOST and SENSOR_HOST.reload)
    or "suricatasc -c reload-rules"
).split())

def _sensing(role):
    host = RANGE.hosts.get(RANGE.roles[role]) or declared.Host()
    return role, host.rules or RULE_PATH, tuple((host.reload or "suricatasc -c reload-rules").split())

CR_EXTRA_SENSORS = tuple(_sensing(role) for role in sorted(RANGE.watches) if role != "sensor")

def waf_layout(shape):
    host = shape.hosts.get(shape.roles.get("gateway", "")) or declared.Host()
    return crs.Layout(host.rules or crs.EXCLUSIONS, host.reload or crs.NGINX_RELOAD, host.pid or crs.NGINX_PID)

CR_WAF = waf_layout(RANGE)
CR_SOURCE = os.environ.get("CR_SOURCE", str(BASE_DIR.parent))
CR_TOPOLOGY = Path(CR_SOURCE) / "deploy" / "topology" / "range-openstack.gns3"
CR_GNS3_URL = os.environ.get("CR_GNS3_URL", "")
CR_GNS3_USER = os.environ.get("CR_GNS3_AUDITOR_USER") or "learner"
CR_GNS3_PASSWORD = os.environ.get("CR_GNS3_AUDITOR_PASSWORD", "")
CR_GNS3_PASSWORD_FILE = Path(os.environ.get("CR_GNS3_AUDITOR_PASSWORD_FILE") or "/run/cr-gns3/auditor-password")
CR_GNS3_WEB_PORT = int(os.environ.get("CR_GNS3_WEB_PORT") or 3080)
CR_GNS3_ADMIN_USER = os.environ.get("CR_GNS3_ADMIN_USER") or "admin"
CR_GNS3_ADMIN_PASSWORD = os.environ.get("CR_GNS3_ADMIN_PASSWORD", "")
CR_GNS3_ADMIN_PASSWORD_FILE = Path(os.environ.get("CR_GNS3_ADMIN_PASSWORD_FILE") or "/run/cr-gns3/admin-password")

CR_SUBSTRATE_OPTIONS = dict(
    {
        "range.openstack.connect": {
            name: os.environ.get(variable, "")
            for name, variable in {
                "keystone": "CR_OPENSTACK_KEYSTONE",
                "user": "CR_OPENSTACK_USER",
                "password": "CR_OPENSTACK_PASSWORD",
                "domain": "CR_OPENSTACK_DOMAIN",
                "project": "CR_OPENSTACK_PROJECT",
                "ssh_user": "CR_OPENSTACK_SSH_USER",
                "ssh_key": "CR_OPENSTACK_SSH_KEY",
                "region": "CR_OPENSTACK_REGION",
                "interface": "CR_OPENSTACK_INTERFACE",
                "base_image": "CR_OPENSTACK_BASE_IMAGE",
                "flavor": "CR_OPENSTACK_FLAVOR",
                "build_flavor": "CR_OPENSTACK_BUILD_FLAVOR",
                "role_flavors": "CR_OPENSTACK_ROLE_FLAVORS",
                "availability_zone": "CR_OPENSTACK_AVAILABILITY_ZONE",
                "subnets": "CR_OPENSTACK_SUBNETS",
                "mtu": "CR_OPENSTACK_MTU",
                "opnsense": "CR_OPNSENSE",
                "build_network": "CR_OPENSTACK_BUILD_NETWORK",
                "platform": "CR_OPENSTACK_PLATFORM",
                "image_tag": "CR_IMAGE_TAG",
                "slots": "CR_OPENSTACK_SLOTS",
                "sideloaded": "CR_SIDELOADED",
            }.items()
        } | {"source": CR_SOURCE},
    }.get(CR_SUBSTRATE, {}),
    declared=RANGE,
)
