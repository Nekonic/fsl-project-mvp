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

                                                                  
ATTACKER_CONTAINER = os.environ.get("ATTACKER_CONTAINER", "fsl-kali")
                                                                           
                          
ATTACKER_SOURCE_CONTAINER = os.environ.get("ATTACKER_SOURCE_CONTAINER", "fsl-proxy")
ATTACKER_LABEL_FILE = os.environ.get("ATTACKER_LABEL_FILE", "/label/active")
ATTACKER_ORIGIN_FILE = os.environ.get("ATTACKER_ORIGIN_FILE", "/label/origin")
ATTACKER_NETWORK = os.environ.get("ATTACKER_NETWORK", "fsl_edge")
ATTACKER_TERMINAL_URL = os.environ.get("ATTACKER_TERMINAL_URL", "http://localhost:7681")

                                                                              
                                                                             
                                                       
TARGET_URL = os.environ.get("TARGET_URL", "http://localhost:8080")
                                                                             
                                                                          
                                                         
PUBLIC_TARGET_URL = os.environ.get("PUBLIC_TARGET_URL", "http://shop.com")

                                                                              
                                                                     
WIKI_READ_LOG = os.environ.get("WIKI_READ_LOG", "/var/log/nginx/read.log")
WIKI_SECRET_PATH = os.environ.get("WIKI_SECRET_PATH", "/runbooks/deploy.html")
TOOL_TARGET_URL = os.environ.get("TOOL_TARGET_URL", "http://waf:8080")
                                                                              
                                                                         
                                                                           
WARGAME_API_URL = os.environ.get("WARGAME_API_URL", "http://juice-shop:3000")
                                                                              
                                                                             
                                                                               
                                                            
TARGET_SETTLE = float(os.environ.get("TARGET_SETTLE", "0.25"))
WARGAME_CASES_DIR = os.environ.get(
    "WARGAME_CASES_DIR", str(BASE_DIR.parent / "redteam" / "cases")
)

                                                                                
ELASTIC_URL = os.environ.get("ELASTIC_URL", "http://elasticsearch:9200")
ELASTIC_INDEX = os.environ.get("ELASTIC_INDEX", "fsl-logs-*")
FSL_SUBSTRATE = os.environ.get("FSL_SUBSTRATE", "range.docker.Docker")
FSL_SUBSTRATE_OPTIONS = {
    "project": os.environ.get("FSL_PROJECT", "fsl"),
    "hosts": {
        "sensor": os.environ.get("SURICATA_CONTAINER", "fsl-suricata"),
        "proxy": os.environ.get("ATTACKER_SOURCE_CONTAINER", "fsl-proxy"),
        "wiki": os.environ.get("WIKI_CONTAINER", "fsl-wiki"),
    },
}

SURICATA_CONTAINER = os.environ.get("SURICATA_CONTAINER", "fsl-suricata")
