from __future__ import annotations

from importlib import import_module
from pathlib import Path

from cr.config import Config, RangeConfig, configured
from sandbox import definitions


def factory(dotted: str):
    module, _, name = dotted.rpartition(".")
    return getattr(import_module(module), name)


def substrate(config: RangeConfig, declared: definitions.Declaration | None = None):
    declared = declared or definitions.read(Path(config.declaration), Path(config.source))
    return factory(config.substrate)(config.openstack, declared)


def whole_range(cfg: Config | None = None):
    return substrate((cfg or configured()).range)


def slot_range(number: int | None, cfg: Config | None = None):
    whole = whole_range(cfg)
    return whole.in_slot(number) if hasattr(whole, "in_slot") and number else whole


def allocation_range(allocation, cfg: Config | None = None):
    return slot_range(allocation.slot, cfg)


def range_of(found, cfg: Config | None = None):
    return allocation_range(found.allocation, cfg)
