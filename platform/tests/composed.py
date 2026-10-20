import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "compose.yaml"

def included():
    return sorted(ROOT.glob("wargames/*/compose.yaml"))

def files():
    return [COMPOSE] + included()

def services():
    merged = {}
    for path in files():
        merged.update(yaml.safe_load(path.read_text()).get("services") or {})
    return merged

def networks():
    return dict(yaml.safe_load(COMPOSE.read_text()).get("networks") or {})

def document():
    return {
        **yaml.safe_load(COMPOSE.read_text()),
        "networks": networks(),
        "services": services(),
    }

def text():
    return "\n".join(path.read_text() for path in files())
