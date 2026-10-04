from pathlib import Path
from unittest.mock import patch

import pytest

import wargames

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parents[2]


def test_every_wargame_model_is_a_known_value():
    for entry in wargames.WARGAMES.values():
        assert entry["objective_model"] in {"loot_verified", "effect_observed", "none"}, entry


def test_the_stack_no_longer_names_juice_shop_or_the_wiki():
    sources = [ROOT / "compose.yaml", ROOT / "platform" / "range" / "declaration.yaml"]
    sources += [p for p in (ROOT / "wargames").rglob("*") if p.is_file()]
    for path in sources:
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "juice-shop" not in text, path
        assert "fsl-wiki" not in text, path


def test_a_none_model_lists_no_objectives(client):
    detect = dict(wargames.WARGAMES["board"], id="detect", objective_model="none")
    with patch.dict(wargames.WARGAMES, {"detect": detect}):
        listed = client.get("/api/wargames/detect/objectives/")
    assert listed.status_code == 200
    assert listed.json() == []


def test_a_none_model_observes_nothing(client):
    detect = dict(wargames.WARGAMES["board"], id="detect", objective_model="none")
    with patch.dict(wargames.WARGAMES, {"detect": detect}):
        created = client.post_json("/api/sessions/", {"scenario": "detect"})
        session_id = created.json()["id"]
        observed = client.post_json(f"/api/sessions/{session_id}/objectives/")
    assert observed.json() == {"achieved": 0, "total": 0}
