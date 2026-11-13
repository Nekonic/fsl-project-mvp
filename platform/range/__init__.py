from __future__ import annotations

from django.conf import settings
from django.utils.module_loading import import_string

def substrate():
    return import_string(settings.CR_SUBSTRATE)(**settings.CR_SUBSTRATE_OPTIONS)
