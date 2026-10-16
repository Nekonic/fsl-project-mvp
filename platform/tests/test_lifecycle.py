import pathlib

import pytest
import yaml

import lifecycle

CASES = pathlib.Path(__file__).resolve().parents[2] / "redteam/cases"

pytestmark = pytest.mark.django_db

@pytest.mark.parametrize("wargame", ["board", "corp"])
def test_every_attack_carries_a_known_stage_and_catalogue_ids_and_benign_traffic_none(wargame):
    for case in yaml.safe_load((CASES / f"{wargame}.yaml").read_text()):
        labels = (case.get("stage"), case.get("technique"), case.get("pattern"))
        if not case["malicious"]:
            assert not any(labels), case["name"]
            continue
        assert labels[0] in lifecycle.STAGES, case["name"]
        assert lifecycle.reference(labels[1]).startswith("https://attack.mitre.org/"), case["name"]
        assert lifecycle.reference(labels[2]).startswith("https://capec.mitre.org/"), case["name"]

def test_the_catalogue_hands_the_console_the_labels_and_where_to_check_them(client):
    listed = client.get("/api/wargames/board/cases/")

    assert listed.status_code == 200
    sqli = next(c for c in listed.json() if c["name"] == "board-sqli-login-bypass")
    assert (sqli["stage"], sqli["technique"], sqli["pattern"]) == ("initial-compromise", "T1190", "CAPEC-66")
    assert sqli["references"] == {
        "technique": "https://attack.mitre.org/techniques/T1190/",
        "pattern": "https://capec.mitre.org/data/definitions/66.html",
    }
    benign = next(c for c in listed.json() if not c["malicious"])
    assert (benign["stage"], benign["technique"], benign["pattern"], benign["references"]) == ("", "", "", {})

def test_a_fired_case_keeps_the_label_it_was_fired_with(client):
    from api.models import Case, Session

    session = Session.objects.create(started_at="2026-09-22T00:00:00Z")
    Case.objects.create(
        session=session, case_id="x", name="sqli-login-bypass", malicious=True,
        stage="initial-compromise", technique="T1190", pattern="CAPEC-66",
        correlation="marker", started_at="2026-09-22T00:00:00Z",
        ended_at="2026-09-22T00:00:01Z",
    )

    listed = client.get(f"/api/sessions/{session.id}/cases/").json()

    assert listed[0]["stage"] == "initial-compromise"
    assert listed[0]["pattern"] == "CAPEC-66", (
        "the label lives only in the case file, so editing the file rewrites "
        "what a session that has already run says it fired"
    )

def test_the_catalogue_says_what_the_range_does_not_reach(client):
    board = next(w for w in client.get("/api/wargames/").json() if w["id"] == "board")
    fired = {case.get("stage") for case in yaml.safe_load((CASES / "board.yaml").read_text())} - {None, ""}

    assert board["covers"] == [stage for stage in lifecycle.STAGES if stage in fired]
    assert board["uncovered"] == [stage for stage in lifecycle.STAGES if stage not in fired], (
        "a range that says nothing about what it cannot show reads as a range "
        "that covers everything"
    )
