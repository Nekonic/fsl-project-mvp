import pathlib

import pytest
import yaml

import lifecycle

CASES = pathlib.Path(__file__).resolve().parents[2] / "redteam/cases/default.yaml"

def cases():
    return yaml.safe_load(CASES.read_text())

def test_the_stages_are_the_ones_the_model_names_and_in_its_order():
    assert lifecycle.STAGES == (
        "initial-reconnaissance",
        "initial-compromise",
        "establish-foothold",
        "escalate-privileges",
        "internal-reconnaissance",
        "move-laterally",
        "maintain-presence",
        "complete-mission",
    ), (
        "the stages are Mandiant's targeted attack life cycle, in its order, "
        "and a stage this range invented would be a stage nobody else reports "
        "against"
    )

def test_every_attack_says_where_in_the_life_cycle_it_belongs():
    unlabelled = [
        case["name"] for case in cases()
        if case["malicious"] and not case.get("stage")
    ]

    assert unlabelled == [], (
        f"{unlabelled} say an attack happened and not what part of an "
        f"intrusion it is, so the range cannot say what it does not cover"
    )

def test_no_case_claims_a_stage_the_model_does_not_have():
    invented = sorted(
        {case.get("stage") for case in cases()} - {None, ""} - set(lifecycle.STAGES)
    )

    assert invented == [], invented

def test_every_attack_carries_an_att_ck_id_and_a_mechanism():
    for case in cases():
        if not case["malicious"]:
            continue
        assert case.get("technique", "").startswith("T"), case["name"]
        assert case.get("pattern", "").startswith("CAPEC-"), case["name"]

def test_benign_traffic_is_not_labelled_as_part_of_an_intrusion():
    mislabelled = [
        case["name"] for case in cases()
        if not case["malicious"] and (case.get("stage") or case.get("technique"))
    ]

    assert mislabelled == [], (
        f"{mislabelled} is traffic that is meant to pass, and a stage on it "
        f"would make the false positives read as part of an attack"
    )

def test_a_label_can_be_checked_against_the_catalogue_that_defines_it():
    assert lifecycle.reference("T1190") == (
        "https://attack.mitre.org/techniques/T1190/"
    )
    assert lifecycle.reference("T1595.002") == (
        "https://attack.mitre.org/techniques/T1595/002/"
    )
    assert lifecycle.reference("CAPEC-66") == (
        "https://capec.mitre.org/data/definitions/66.html"
    )

def test_a_label_from_no_catalogue_gets_no_link_rather_than_a_broken_one():
    assert lifecycle.reference("SQLi") == ""
    assert lifecycle.reference("") == ""

def test_every_id_any_case_uses_resolves_to_a_catalogue():
    for case in cases():
        for field in ("technique", "pattern"):
            value = case.get(field) or ""
            if value:
                assert lifecycle.reference(value), f"{case['name']}: {value}"

pytestmark = pytest.mark.django_db

def test_the_catalogue_hands_the_console_the_labels_and_where_to_check_them(client):
    listed = client.get("/api/wargames/juice-shop/cases/")

    assert listed.status_code == 200
    sqli = next(c for c in listed.json() if c["name"] == "sqli-login-bypass")
    assert sqli["stage"] == "initial-compromise"
    assert sqli["technique"] == "T1190"
    assert sqli["pattern"] == "CAPEC-66"
    assert sqli["references"] == {
        "technique": "https://attack.mitre.org/techniques/T1190/",
        "pattern": "https://capec.mitre.org/data/definitions/66.html",
    }

def test_benign_traffic_comes_back_with_no_labels_at_all(client):
    listed = client.get("/api/wargames/juice-shop/cases/")

    benign = next(c for c in listed.json() if not c["malicious"])
    assert (benign["stage"], benign["technique"], benign["pattern"]) == ("", "", "")
    assert benign["references"] == {}

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
    listed = client.get("/api/wargames/").json()
    juice = next(w for w in listed if w["id"] == "juice-shop")

    assert juice["covers"] == [
        "initial-reconnaissance", "initial-compromise", "complete-mission",
    ], "the stages it covers are not in life cycle order"
    assert juice["uncovered"] == [
        "establish-foothold", "escalate-privileges", "internal-reconnaissance",
        "move-laterally", "maintain-presence",
    ], (
        "a range that says nothing about what it cannot show reads as a range "
        "that covers everything. There is no code execution on the target, so "
        "there is no foothold and nothing to escalate"
    )

def test_every_stage_a_case_or_the_catalogue_names_has_a_word_for_it():
    strings = (
        pathlib.Path(__file__).resolve().parents[1]
        / "console/templates/console/strings.html"
    ).read_text()

    for stage in lifecycle.STAGES:
        assert f'"stage.{stage}"' in strings, (
            f"{stage} would be drawn as its own id, which is not a word in "
            f"either language"
        )
