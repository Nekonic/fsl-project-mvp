import hashlib
import json
import threading

from django.conf import settings

import gns3
import topology
from api import customers
from range.ports import RangeUnavailable

SLOT = "slot"

_guard = threading.Lock()
_turns: dict[str, threading.Lock] = {}
_running: set[str] = set()
_loaded: dict[str, str] = {}
_failed: dict[str, str] = {}

def called(kind: str, number: int, wargame: str) -> str:
    return f"{kind} {number} {wargame}"

def wargame_of(key: str) -> str:
    return key.rsplit(" ", 1)[1]

def _salt(key: str) -> str:
    return key.replace(" ", "-")

def project_id(key: str) -> str:
    return topology.renamed(gns3.local()["project_id"], _salt(key))

def _customers_prefer(wargame: str) -> tuple[str, ...]:
    try:
        weights = customers.declared(wargame)["origins"]
    except customers.NoTraffic:
        return ()
    declared = settings.RANGE
    subnets = {origin.id: origin.subnet for origin in declared.origins if origin.id != declared.default_origin}
    return tuple(subnets[origin] for origin in sorted(weights, key=lambda origin: (-weights[origin], origin))
                 if origin in subnets and weights[origin] > 0)

def learner(wargame: str) -> topology.Learner:
    declared = settings.RANGE
    return topology.learner(declared, wargame, declared.roles["attacker"], _customers_prefer(wargame))

def template(wargame: str) -> dict:
    return topology.for_wargame(gns3.local(), learner(wargame))

def document(key: str, found) -> dict:
    return topology.labelled(gns3.local(), learner(wargame_of(key)), found, _salt(key), key)

def _turn(key: str) -> threading.Lock:
    with _guard:
        return _turns.setdefault(key, threading.Lock())

def publish(key: str, read) -> str:
    with _turn(key):
        return _published(key, read)

def _published(key: str, read) -> str:
    drawn = document(key, read())
    fingerprint = hashlib.sha256(json.dumps(drawn, sort_keys=True).encode()).hexdigest()
    if _loaded.get(key) == fingerprint and gns3.status(drawn["project_id"]) == "opened":
        return "opened"
    loaded = gns3.publish(drawn)
    _loaded[key] = fingerprint
    _failed.pop(key, None)
    return loaded

def loaded(key: str) -> bool:
    return key in _loaded

def failure(key: str) -> str:
    return _failed.get(key, "")

def tidy(kind: str, live: list[str]) -> list[str]:
    kept = {project_id(key) for key in live}
    removed = gns3.remove_except(f"{gns3.local()['name']} {kind} ", kept)
    for key in [key for key in _loaded if key.startswith(kind) and key not in live]:
        _loaded.pop(key, None)
    return removed

def _run(key: str, read, kind: str, live: list[str], turn: threading.Lock) -> None:
    try:
        try:
            _published(key, read)
        finally:
            turn.release()
        tidy(kind, live)
    except (gns3.Unavailable, RangeUnavailable) as exc:
        _failed[key] = str(exc)
    finally:
        with _guard:
            _running.discard(key)

def begin(key: str, read, kind: str, live: list[str]):
    with _guard:
        if key in _running:
            return None
        _running.add(key)
    turn = _turn(key)
    turn.acquire()
    worker = threading.Thread(target=_run, args=(key, read, kind, live, turn), name=f"cr-map-{_salt(key)}",
                              daemon=True)
    worker.start()
    return worker

def served(key: str, read) -> dict:
    wanted = project_id(key)
    try:
        with _turn(key):
            if gns3.status(wanted) != "opened":
                _published(key, read)
    except (gns3.Unavailable, RangeUnavailable) as exc:
        _failed[key] = str(exc)
        return {**gns3.project(template(wargame_of(key))),
                "detail": f"the map of your {key} could not be loaded: {exc}"[:300]}
    return gns3.project({**template(wargame_of(key)), "project_id": wanted})
