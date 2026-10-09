import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "compose.yaml"
SESSION = ROOT / "session.yaml"

def included():
    top = yaml.safe_load(SESSION.read_text())
    return [SESSION.parent / path for path in top.get("include") or []]

def files():
    return [COMPOSE, SESSION] + included()

def services():
    merged = {}
    for path in files():
        merged.update(yaml.safe_load(path.read_text()).get("services") or {})
    return merged

def document():
    return {**yaml.safe_load(COMPOSE.read_text()), "services": services()}

def text():
    return "\n".join(path.read_text() for path in files())
