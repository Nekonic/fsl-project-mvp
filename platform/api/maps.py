import hashlib
import json
import threading

from django.conf import settings

import gns3
import topology
from api import customers
from range.ports import RangeUnavailable
from console.strings import LANGUAGES

SLOT = "slot"
SESSION = "session"
SNAT = "snat"

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

def _base(language: str) -> str:
    return gns3.local(language)["name"].partition(topology.KOREAN_SUFFIX)[0]

def project_id(key: str, language: str) -> str:
    return topology.renamed(gns3.local(language)["project_id"], _salt(key))

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
    customers_from = declared.roles["attacker"] if settings.ATTACKER_ORIGIN_MODE == SNAT else ""
    return topology.learner(declared, wargame, customers_from, _customers_prefer(wargame))

def template(wargame: str, language: str = gns3.ENGLISH) -> dict:
    return topology.for_wargame(gns3.local(language), learner(wargame))

def documents(key: str, found) -> dict[str, dict]:
    drawn = learner(wargame_of(key))
    return {language: topology.labelled(gns3.local(language), drawn, found, _salt(key), key)
            for language in LANGUAGES}

def publish(key: str, read) -> dict[str, str]:
    with _guard:
        turn = _turns.setdefault(key, threading.Lock())
    with turn:
        return _published(key, read)

def _published(key: str, read) -> dict[str, str]:
    drawn = documents(key, read())
    fingerprint = hashlib.sha256(json.dumps(drawn, sort_keys=True).encode()).hexdigest()
    if _loaded.get(key) == fingerprint and all(
            gns3.status(document["project_id"]) == "opened" for document in drawn.values()):
        return {language: "opened" for language in drawn}
    loaded = {language: gns3.publish(document) for language, document in drawn.items()}
    _loaded[key] = fingerprint
    _failed.pop(key, None)
    return loaded

def tidy(kind: str, live: list[str]) -> list[str]:
    kept = {project_id(key, language) for key in live for language in LANGUAGES}
    removed = []
    for language in LANGUAGES:
        removed += gns3.remove_except(f"{_base(language)} {kind} ", kept)
    for key in [key for key in _loaded if key.startswith(kind) and key not in live]:
        _loaded.pop(key, None)
    return removed

def tidied(kind: str, live: list[str]) -> None:
    try:
        tidy(kind, live)
    except gns3.Unavailable:
        pass

def _run(key: str, read, kind: str, live: list[str]) -> None:
    try:
        publish(key, read)
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
    worker = threading.Thread(target=_run, args=(key, read, kind, live), name=f"fsl-map-{_salt(key)}", daemon=True)
    worker.start()
    return worker

def served(key: str, language: str, read) -> dict:
    wanted = project_id(key, language)
    if gns3.status(wanted) != "opened":
        try:
            publish(key, read)
        except (gns3.Unavailable, RangeUnavailable) as exc:
            _failed[key] = str(exc)
            return {**gns3.project(language, template(wargame_of(key), language)),
                    "detail": f"the map of your {key} could not be loaded: {exc}"[:300]}
    return gns3.project(language, {**template(wargame_of(key), language), "project_id": wanted})
