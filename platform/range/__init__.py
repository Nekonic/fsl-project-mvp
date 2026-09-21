from __future__ import annotations

from django.conf import settings
from django.utils.module_loading import import_string

def substrate():
    return import_string(settings.FSL_SUBSTRATE)(**settings.FSL_SUBSTRATE_OPTIONS)
