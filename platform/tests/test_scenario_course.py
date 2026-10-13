import copy
import re
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from django.utils import timezone

import scenarios
import traffic
import wargames
from api import scenario_run
from api.models import Case, Session
from console import strings
from tests.test_scenario_engine import (COURSE, DUMPED, HELD, SQLMAP, Stack, alert, customer, firing, judging, known,
                                        opened, window_judged)

pytestmark = pytest.mark.django_db

RULES = Path(__file__).resolve().parents[2] / "deploy" / "suricata" / "rules"
TRAFFIC = traffic.checked(wargames.yaml.safe_load((Path(__file__).resolve().parents[2] / "wargames" / "board" /
                                                   "traffic.yaml").read_text()), "traffic.yaml")
STOCK = ["/?sort=posts_post.id' WHERE 4813=4813 AND SLEEP(5)#",
         "/?sort=posts_post.id OR NOT 7322=4689# Frad",
         "/?sort=posts_post.id) AS HADP WHERE 7429=7429 AND EXTRACTVALUE(2467,CASE WHEN (2467=8301) THEN 2467 "
         "ELSE 0x3A END)-- wljx"]
TAMPER = ["/?sort=posts_post.id`)/**/wHeRE/**/1922=1922/**/RlIKE/**/(seLECt/**/1305/**/From/**/(seLECt(SLeep(5)))YjHb)--/**/Nbap",
          "/?sort=posts_post.id'/**/aND/**/3161/**/betweEn/**/1566/**/aND/**/1566--/**/kCBY",
          "/?sort=posts_post.id\"/**/And/**/1831=beNCHmARk(5000000,MD5(0x484d4c5a))/**/And/**/\"JSDw\"=\"JSDw"]
SORTED = "/?sort=-created_at"

def checked(one):
    wargames.checked_scenarios([one], known(), "test", tuple(wargames.WARGAMES["board"]["defense"]),
                               set(TRAFFIC["profiles"]))

def keys_of(one):
    text = one["text"]
    keys = [f"{text}.title", f"{text}.practise", *one["briefing"].values()]
    keys += [f"{text}.card.{card['id']}.{part}" for card in one.get("cards") or [] for part in ("title", "body")]
    keys += [f"{text}.hint.{hint}" for hint in one.get("hints") or []]
    for step in one.get("steps") or []:
        keys += [f"{text}.{part}.{step['id']}" for part in ("label", "coach", "nudge", "ok")]
    return keys

def rule_of(name, sid):
    line = next(line for line in (RULES / name).read_text().splitlines() if f"sid:{sid};" in line)
    buffer = re.search(r"(http\.[a-z_.]+);\s*pcre", line).group(1)
    pattern = re.search(r'pcre:"/(.*)/([a-z]*)";', line)
    return buffer, re.compile(pattern.group(1), re.IGNORECASE if "i" in pattern.group(2) else 0)

@pytest.mark.parametrize("scenario_id", COURSE)
def test_every_scenario_validates_and_has_its_words_in_both_languages(scenario_id):
    one = copy.deepcopy(wargames.scenario_run(scenario_id))
    checked(one)
    table = {language: strings.shown()[language] for language in strings.LANGUAGES}

    missing = {language: [key for key in keys_of(one) if key not in table[language]] for language in table}
    assert missing == {"en": [], "ko": []}
    assert one["traffic"]["profile"] in TRAFFIC["profiles"]
    assert all(dict(known())[attack["case"]] for attack in one["attacks"])
    card = wargames.scenario_card(one)
    assert "attacks" not in card and not any(attack["case"] in str(card) for attack in one["attacks"])

def test_the_judgement_scenarios_inherit_a_waf_whose_totals_were_taken_out():
    for scenario_id in ("1.2", "1.3"):
        posture = wargames.defense("board", wargames.scenario_run(scenario_id)["defense"])
        assert posture["waf"]["paranoia"] == 2
        assert sorted(entry["rule_id"] for entry in posture["waf"]["exclusions"]) == [949110, 959100]
    busy = wargames.scenario_run("1.3")
    patterns = {case["pattern"] for case in wargames.cases("board") if case["name"] in
                {attack["case"] for attack in busy["attacks"]}}
    assert patterns == {"CAPEC-66", "CAPEC-63", "CAPEC-126"}
    assert {attack["origin"] for attack in busy["attacks"]} == {"kr"}
    assert busy["traffic"]["rate"] > wargames.scenario_run("1.2")["traffic"]["rate"]
    assert wargames.scenario_card(busy)["patterns"] == ["CAPEC-126", "CAPEC-63", "CAPEC-66"]
    assert wargames.scenario_card(wargames.scenario_run("1.2"))["patterns"] == []

def test_the_threshold_scenario_starts_untuned_at_paranoia_level_3_and_finishes_at_the_crs_defaults():
    one = wargames.scenario_run("2.3")
    posture = wargames.defense("board", one["defense"])

    assert posture["waf"] == {"paranoia": 3, "thresholds": {"inbound": 10000, "outbound": 10000}}
    assert one["completion"] == {"served": "all", "held": "all", "thresholds": {"inbound": 5, "outbound": 4}}
    assert "comment" in TRAFFIC["profiles"][one["traffic"]["profile"]]

def test_the_broken_rule_reads_the_body_and_the_fixed_one_catches_stock_sqlmap_and_not_a_sort():
    buffer, pattern = rule_of("broken-sort.rules", 9000101)
    step = next(step for step in wargames.scenario_run("3.1")["steps"] if step["id"] == "fix")
    fixed = re.search(r'pcre:"/(.*)/i"', step["rule"]).group(1)

    assert buffer == "http.request_body"
    assert "http.uri;" in step["rule"] and pattern.pattern == fixed
    assert all(re.search(fixed, uri, re.I) for uri in STOCK + TAMPER) and not re.search(fixed, SORTED, re.I)

def test_the_spelled_rule_catches_the_stock_run_and_misses_every_tamper_request():
    buffer, pattern = rule_of("spaced-sort.rules", 9000101)
    one = wargames.scenario_run("3.3")

    assert buffer == "http.uri" and wargames.defense("board", one["defense"])["suricata"] == "spaced-sort.rules"
    assert all(pattern.search(uri) for uri in STOCK)
    assert not any(pattern.search(uri) for uri in TAMPER + [SORTED])
    assert {attack["case"] for attack in one["attacks"]} == {SQLMAP, "board-sqli-orderby-sqlmap-tamper"}

def test_the_detection_postures_leave_the_sort_attack_to_the_learner():
    for scenario_id, ruleset in (("3.2", "no-uri-sqli.rules"), ("3.4", "local.rules")):
        assert wargames.defense("board", wargames.scenario_run(scenario_id)["defense"])["suricata"] == ruleset
    assert "sid:9000001;" not in (RULES / "no-uri-sqli.rules").read_text()
    body = next(line for line in (RULES / "local.rules").read_text().splitlines() if "sid:9000003;" in line)
    assert "http.uri;" in body
    assert {attack["case"] for attack in wargames.scenario_run("3.4")["attacks"]} == {
        "board-xss-img-onerror-in-comment", "board-xss-script-tag-in-search"}

def test_the_unknown_scenario_sends_an_unseen_variant_and_customers_who_post_code():
    one = wargames.scenario_run("4.1")
    seen = {attack["case"] for other in wargames.scenarios("board") if other["id"] != "4.1"
            for attack in other["attacks"]}

    assert "board-sqli-orderby-sqlmap-versioned" in {attack["case"] for attack in one["attacks"]}
    assert "board-sqli-orderby-sqlmap-versioned" not in seen
    assert "comment-code" in TRAFFIC["profiles"][one["traffic"]["profile"]]
    assert (one["guidance"], one.get("hints"), one.get("cards")) == ("none", None, None)

def test_the_final_check_refuses_thresholds_above_the_ones_it_names():
    session = opened("2.3")
    session.waf = {"paranoia": 3, "exclusions": [], "thresholds": {"inbound": 50, "outbound": 4}}
    session.save(update_fields=["waf"])

    result = window_judged(session)

    assert result["passed"] is False
    assert ["scenario.fail.threshold", [50, 4, 5, 4]] in result["reasons"]

@pytest.mark.parametrize("waf", [
    {"paranoia": 3, "exclusions": [], "thresholds": {"inbound": 5, "outbound": 4}},
    {"paranoia": 3, "exclusions": []},
])
def test_the_final_check_passes_at_the_crs_default_thresholds(waf):
    session = opened("2.3")
    session.waf = waf
    session.save(update_fields=["waf"])

    result = window_judged(session)

    assert result["passed"] is True, result

def test_thresholds_in_a_completion_are_validated():
    one = copy.deepcopy(wargames.scenario_run("2.3"))
    with pytest.raises(wargames.InvalidCatalogue, match="thresholds"):
        checked(dict(one, completion={"served": "all", "held": "all", "thresholds": {"inbound": 0}}))
    with pytest.raises(wargames.InvalidCatalogue, match="completion"):
        checked(dict(one, completion={"served": "all", "held": "all", "pattern": "judged"}))

def attack_item(client, session, name, pattern, loot=()):
    case = Case.objects.create(session=session, case_id=str(uuid.uuid4()), name=name, malicious=True,
                               pattern=pattern, correlation="marker", started_at=timezone.now(),
                               ended_at=timezone.now(), meta={"scheduled": session.course_scenario, "loot": list(loot)})
    alert(session, case.case_id, source="suricata", rule="9000003")
    items = client.get(f"/api/sessions/{session.pk}/triage/").json()["items"]
    return next(item["item"] for item in items if item["item"] == scenarios.item_id(session.browse_marker, case.case_id))

def test_a_busy_evening_judges_the_kind_of_each_attack(client):
    session = opened("1.3")
    item = attack_item(client, session, "board-xss-script-tag-in-search", "CAPEC-63")

    def judged(**body):
        return client.post_json(f"/api/sessions/{session.pk}/triage/",
                                {"item": item, "verdict": "attack", "succeeded": False, **body})

    assert judged().status_code == 400
    assert judged(pattern="CAPEC-999").status_code == 400
    wrong = judged(pattern="CAPEC-66").json()
    assert (wrong["right"], wrong["verdict_right"], wrong["pattern_right"]) == (False, True, False)
    right = judged(pattern="CAPEC-63").json()
    assert (right["right"], right["pattern_right"]) == (True, True)
    session.refresh_from_db()
    assert session.scenario_state["triage"][item]["pattern"] == "CAPEC-63"
    listed = client.get(f"/api/sessions/{session.pk}/triage/").json()["items"]
    assert "CAPEC" not in str([{key: value for key, value in one.items() if key != "judged"} for one in listed])

def test_a_scenario_that_does_not_judge_the_kind_ignores_it(client):
    session = opened("1.2")
    item = attack_item(client, session, SQLMAP, "CAPEC-66", loot=["admin"])

    judged = judging(client, session, item, "attack", True).json()

    assert judged["right"] is True and "pattern_right" not in judged

def person_scenario(**changed):
    one = copy.deepcopy(wargames.scenario_run("4.1"))
    one.update({"red": "person", "attacks": []}, **changed)
    return one

def test_a_scenario_may_leave_the_red_team_to_a_person_and_then_needs_no_schedule():
    checked(person_scenario())
    assert wargames.scenario_card(person_scenario())["red"] == "person"
    with pytest.raises(wargames.InvalidCatalogue, match="attacks"):
        checked(dict(person_scenario(), red="schedule"))
    with pytest.raises(wargames.InvalidCatalogue, match="red"):
        checked(person_scenario(red="robot"))

@pytest.mark.parametrize("loot, passed", [([], True), (["admin"], False)])
def test_a_person_s_attack_inside_the_window_is_judged_like_a_scheduled_one(loot, passed):
    session = opened("4.1")
    with patch("api.scenario_run.declared_of", lambda session: person_scenario()):
        Session.objects.filter(pk=session.pk).update(scenario_state=dict(session.scenario_state, schedule=[]))
        session.refresh_from_db()
        scenario_run.start_window(session, "learner", timezone.now() - timedelta(minutes=6))
        session.refresh_from_db()
        window = session.scenario_state["windows"][-1]
        Case.objects.create(session=session, case_id=str(uuid.uuid4()), name=SQLMAP, malicious=True,
                            correlation="marker", started_at=scenarios.at(window["started_at"]) + timedelta(seconds=30),
                            ended_at=scenarios.at(window["started_at"]) + timedelta(seconds=90), meta={"loot": loot})
        with patch("api.scenario_run.customers.refresh", lambda session, adapter: None), \
                patch("api.views._snapshot_waf", lambda session, **taken: None), \
                patch("api.scenario_run._observe", lambda session, now: None):
            scenario_run.tick(scenarios.at(window["ends_at"]) + timedelta(seconds=1))
    session.refresh_from_db()
    result = session.scenario_state["windows"][-1]["result"]

    assert (result["passed"], result["attacks"]) == (passed, 1), result

def detection_window(session, *, alerted_by, customer_alert=False):
    begun = scenarios.at(session.scenario_state["opened_at"]) + timedelta(seconds=300)
    scenario_run.start_window(session, "learner", begun)
    session.refresh_from_db()
    window = session.scenario_state["windows"][-1]
    start, end = scenarios.at(window["started_at"]), scenarios.at(window["ends_at"])
    patches, _ = firing(HELD)
    with Stack(patches), patch("api.scenario_run.judge_window", lambda session: None):
        scenario_run.tick(end - timedelta(seconds=1))
    session.refresh_from_db()
    for entry in session.scenario_state["schedule"]:
        if entry.get("case_id") and entry["in_window"]:
            alert(session, entry["case_id"], source=alerted_by, rule="9000102")
    sent = customer(session, start + timedelta(seconds=20))
    if customer_alert:
        alert(session, sent.marker, source="suricata", rule="9000102")
    signature = "FSL SQLi attempt - sort is not a column name"
    session.detections.filter(source="suricata").update(signature=signature)
    with Stack(patches), patch("api.scenario_run.customers.refresh", lambda session, adapter: None), \
            patch("api.views._snapshot_waf", lambda session, **taken: None):
        scenario_run.tick(end + timedelta(seconds=1))
    session.refresh_from_db()
    return session.scenario_state["windows"][-1]["result"]

def test_a_detection_window_passes_when_every_attack_draws_an_ids_alert_naming_sql_and_customers_stay_quiet():
    result = detection_window(opened("3.2"), alerted_by="suricata")

    assert result["passed"] is True, result

def test_a_detection_window_fails_when_only_the_waf_saw_the_attack():
    result = detection_window(opened("3.2"), alerted_by="modsecurity")

    assert result["passed"] is False
    assert ["scenario.fail.undetected", [SQLMAP]] in result["reasons"]

def test_a_detection_window_fails_when_a_customer_draws_an_ids_alert():
    result = detection_window(opened("3.2"), alerted_by="suricata", customer_alert=True)

    assert result["passed"] is False
    assert ["scenario.fail.noisy", [1]] in result["reasons"]

def test_an_availability_window_leaked_by_the_unseen_variant_fails_on_both_scores():
    result = window_judged(opened("4.1"), output=DUMPED)

    assert result["passed"] is False
    assert any(reason[0] == "scenario.fail.leaked" for reason in result["reasons"])

def test_a_writer_waits_for_the_store_instead_of_failing_a_scheduled_attack():
    from django.conf import settings

    assert settings.DATABASES["default"]["OPTIONS"]["timeout"] >= 30
