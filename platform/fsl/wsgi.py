import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fsl.settings")

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.wsgi import get_wsgi_application

if not settings.DEBUG and not os.environ.get("DJANGO_SECRET_KEY"):
    raise ImproperlyConfigured(
        "refusing to serve: DJANGO_SECRET_KEY is unset and DEBUG is off. Set "
        "one, or set DJANGO_DEBUG=1 if this is the local lab."
    )

application = get_wsgi_application()
