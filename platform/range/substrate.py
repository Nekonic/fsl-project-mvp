from __future__ import annotations

from importlib import import_module
from pathlib import Path

from cr.config import RangeConfig
from range import declaration


def factory(dotted: str):
    module, _, name = dotted.rpartition(".")
    return getattr(import_module(module), name)


def substrate(config: RangeConfig, declared: declaration.Declaration | None = None):
    declared = declared or declaration.read(Path(config.declaration), Path(config.source))
    return factory(config.substrate)(config.openstack, declared)
