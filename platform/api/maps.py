import dataclasses
import hashlib
import json
import threading

from django.conf import settings

import gns3
import topology
from range.ports import RangeUnavailable
from console.strings import LANGUAGES

SLOT = "slot"
SESSION = "session"

_guard = threading.Lock()
_turns: dict[str, threading.Lock] = {}
_running: set[str] = set()
_loaded: dict[str, str] = {}
_failed: dict[str, str] = {}
_found: dict[str, list] = {}

def called(kind: str, number: int) -> str:
    return f"{kind} {number}"

def _salt(key: str) -> str:
    return key.replace(" ", "-")

def _base(language: str) -> str:
    return gns3.local(language)["name"].partition(topology.KOREAN_SUFFIX)[0]

def project_id(key: str, language: str) -> str:
    return topology.renamed(gns3.local(language)["project_id"], _salt(key))

def _first() -> str:
    declared = settings.RANGE
    return next((origin.subnet for origin in declared.origins if origin.id == declared.default_origin), "")

def shown(found) -> list:
    called = topology.shown_as(settings.RANGE)
    return [dataclasses.replace(one, host=called.get(one.host, one.host)) for one in found]

def documents(key: str, found) -> dict[str, dict]:
    return {language: topology.labelled(gns3.local(language), shown(found), _salt(key), key, _first())
            for language in LANGUAGES}

def addresses(key: str, read) -> dict:
    if key not in _found:
        _found[key] = shown(read())
    return topology.addressing(gns3.local(), settings.RANGE, _found[key], _first())

def publish(key: str, read) -> dict[str, str]:
    with _guard:
        turn = _turns.setdefault(key, threading.Lock())
    with turn:
        return _published(key, read)

def _published(key: str, read) -> dict[str, str]:
    found = read()
    _found[key] = shown(found)
    drawn = documents(key, found)
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
    for key in [key for key in {*_loaded, *_found} if key.startswith(kind) and key not in live]:
        _loaded.pop(key, None)
        _found.pop(key, None)
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
            return {**gns3.project(language), "detail": f"the map of your {key} could not be loaded: {exc}"[:300]}
    return gns3.project(language, {**gns3.local(language), "project_id": wanted})
