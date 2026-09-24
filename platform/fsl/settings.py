import os
from pathlib import Path

from range import declared

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

RANGE = declared.read()

ATTACKER_CONTAINER = RANGE.roles["attacker"]
ATTACKER_SOURCE_CONTAINER = RANGE.roles["proxy"]
ATTACKER_LABEL_FILE = os.environ.get("ATTACKER_LABEL_FILE", "/label/active")
ATTACKER_ORIGIN_FILE = os.environ.get("ATTACKER_ORIGIN_FILE", "/label/origin")
ATTACKER_TERMINAL_URL = os.environ.get("ATTACKER_TERMINAL_URL", "http://localhost:7681")

                                                                              
                                                                             
                                                       
TARGET_URL = os.environ.get("TARGET_URL", "http://localhost:8080")
                                                                             
                                                                          
                                                         
PUBLIC_TARGET_URL = os.environ.get("PUBLIC_TARGET_URL", "http://shop.com")

                                                                              
                                                                     
WIKI_READ_LOG = os.environ.get("WIKI_READ_LOG", "/var/log/nginx/read.log")
WIKI_SECRET_PATH = os.environ.get("WIKI_SECRET_PATH", "/runbooks/deploy.html")
                                                                              
                                                                         
                                                                           
WARGAME_API_URL = os.environ.get("WARGAME_API_URL", "http://juice-shop:3000")
                                                                              
                                                                             
                                                                               
                                                            
TARGET_SETTLE = float(os.environ.get("TARGET_SETTLE", "0.25"))
WARGAME_CASES_DIR = os.environ.get(
    "WARGAME_CASES_DIR", str(BASE_DIR.parent / "redteam" / "cases")
)

                                                                                
ELASTIC_URL = os.environ.get("ELASTIC_URL", "http://elasticsearch:9200")
ELASTIC_INDEX = os.environ.get("ELASTIC_INDEX", "fsl-logs-*")
FSL_SENSOR_RELOAD = tuple(
    os.environ.get("FSL_SENSOR_RELOAD", "kill -USR2 1").split()
)

FSL_SUBSTRATE = os.environ.get("FSL_SUBSTRATE", "range.docker.Docker")
FSL_SUBSTRATE_OPTIONS = dict(
    {
        "range.docker.Docker": {"project": os.environ.get("FSL_PROJECT", "fsl")},
        "range.openstack.connect": {
            "keystone": os.environ.get("FSL_OPENSTACK_KEYSTONE", ""),
            "user": os.environ.get("FSL_OPENSTACK_USER", ""),
            "password": os.environ.get("FSL_OPENSTACK_PASSWORD", ""),
            "project": os.environ.get("FSL_OPENSTACK_PROJECT", ""),
            "ssh_user": os.environ.get("FSL_OPENSTACK_SSH_USER", ""),
            "ssh_key": os.environ.get("FSL_OPENSTACK_SSH_KEY", ""),
            "ssh_config": os.environ.get("FSL_OPENSTACK_SSH_CONFIG", ""),
            "region": os.environ.get("FSL_OPENSTACK_REGION", "RegionOne"),
            "interface": os.environ.get("FSL_OPENSTACK_INTERFACE", "public"),
        },
    }.get(FSL_SUBSTRATE, {}),
    declared=RANGE,
)
