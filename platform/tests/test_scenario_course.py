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
from tests.test_scenario_engine import (COURSE, DUMPED, HELD, SQLMAP, Stack, alert, customer, firing, known,
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

def test_the_broken_rule_reads_the_body_and_the_answer_s_buffer_fix_catches_stock_sqlmap_and_not_a_sort():
    buffer, pattern = rule_of("broken-sort.rules", 9000101)
    answer = strings.both("scenario.fixrule.answer.fix")["en"]

    assert buffer == "http.request_body"
    assert all(word in answer for word in ("9000101", "http.request_body", "http.uri"))
    assert all(pattern.search(uri) for uri in STOCK + TAMPER) and not pattern.search(SORTED)

def test_the_spelled_rule_catches_the_stock_run_and_misses_every_tamper_request():
    buffer, pattern = rule_of("spaced-sort.rules", 9000101)
    one = wargames.scenario_run("3.3")

    assert buffer == "http.uri" and wargames.defense("board", one["defense"])["suricata"] == "spaced-sort.rules"
    assert all(pattern.search(uri) for uri in STOCK)
    assert not any(pattern.search(uri) for uri in TAMPER + [SORTED])
    assert {attack["case"] for attack in one["attacks"]} == {SQLMAP, "board-sqli-orderby-sqlmap-tamper"}

@pytest.mark.parametrize("waf, refused", [
    ({"paranoia": 3, "exclusions": [], "thresholds": {"inbound": 5, "outbound": 4}}, None),
    ({"paranoia": 3, "exclusions": []}, None),
    ({"paranoia": 3, "exclusions": [], "thresholds": {"inbound": 50, "outbound": 4}},
     ["scenario.fail.threshold", [50, 4, 5, 4]]),
], ids=["crs-defaults", "no-thresholds-set", "raised-above"])
def test_the_final_check_passes_only_at_or_below_the_thresholds_it_names(waf, refused):
    session = opened("2.3")
    session.waf = waf
    session.save(update_fields=["waf"])

    result = window_judged(session)

    assert result["passed"] is (refused is None), result
    assert refused is None or refused in result["reasons"]

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

def person_scenario(**changed):
    one = copy.deepcopy(wargames.scenario_run("4.1"))
    one.update({"red": "person", "attacks": []}, **changed)
    return one

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

@pytest.mark.parametrize("alerted_by, customer_alert, refused", [
    ("suricata", False, None),
    ("modsecurity", False, ["scenario.fail.undetected", [SQLMAP]]),
    ("suricata", True, ["scenario.fail.noisy", [1]]),
], ids=["ids-saw-it", "only-the-waf-saw-it", "a-customer-drew-an-ids-alert"])
def test_a_detection_window_passes_only_when_the_ids_sees_every_attack_and_no_customer(
        alerted_by, customer_alert, refused):
    result = detection_window(opened("3.2"), alerted_by=alerted_by, customer_alert=customer_alert)

    assert result["passed"] is (refused is None), result
    assert refused is None or refused in result["reasons"]

def test_an_availability_window_leaked_by_the_unseen_variant_fails_on_both_scores():
    result = window_judged(opened("4.1"), output=DUMPED)

    assert result["passed"] is False
    assert any(reason[0] == "scenario.fail.leaked" for reason in result["reasons"])

def test_a_writer_waits_for_the_store_instead_of_failing_a_scheduled_attack():
    from django.conf import settings

    assert settings.DATABASES["default"]["OPTIONS"]["timeout"] >= 30

def test_a_judgement_window_judges_the_items_listed_when_it_opened_not_ones_that_arrive_later_with_an_earlier_time():
    session = opened("1.1")
    shown = str(uuid.uuid4())
    customer(session, timezone.now() - timedelta(minutes=3), status=403, marker=shown)
    alert(session, shown, at=timezone.now() - timedelta(minutes=3))
    item = scenario_run._items(session)[0]["item"]
    scenario_run._update(session.pk, lambda state, held: state["triage"].update(
        {item: {"verdict": "customer", "succeeded": None, "right": True, "tries": 1, "wrong": 0, "first_right": True,
                "at": "x"}}))
    session.refresh_from_db()
    begun = timezone.now() - timedelta(minutes=2)
    scenario_run.start_window(session, "learner", begun)
    late = str(uuid.uuid4())
    customer(session, begun - timedelta(seconds=40), status=403, marker=late)
    alert(session, late, at=begun - timedelta(seconds=40))
    session.refresh_from_db()
    window = session.scenario_state["windows"][-1]

    assert window["items"] == [item]
    patches, _ = firing(HELD)
    with Stack(patches), patch("api.scenario_run.customers.refresh", lambda session, adapter: None), \
            patch("api.views._snapshot_waf", lambda session, **taken: None), \
            patch("api.scenario_run._observe", lambda session, now: None):
        scenario_run.tick(scenarios.at(window["ends_at"]) + timedelta(seconds=1))
    session.refresh_from_db()
    assert session.scenario_state["windows"][-1]["result"]["passed"] is True

def test_a_rules_step_passes_on_a_changed_rule_as_well_as_a_new_one():
    import lesson

    broken = (RULES / "broken-sort.rules").read_text()
    fixed = broken.replace('http.request_body; pcre:"/[?&]sort=', 'http.uri; pcre:"/[?&]sort=')
    spaced = broken.replace("sid:9000101; rev:1;)", "sid:9000101;  rev:1;)")

    assert lesson.added_rules(broken, broken) == []
    assert lesson.added_rules(spaced, broken) == []
    assert lesson.added_rules(fixed, broken) == [9000101]
    added = next(line for line in fixed.splitlines() if "sid:9000101;" in line).replace("sid:9000101;", "sid:9000102;")
    assert lesson.added_rules(f"{broken.rstrip()}\n{added}\n", broken) == [9000102]

def test_a_detection_debrief_counts_and_shows_only_the_ids_alerts(client):
    session = opened("3.2")
    case = Case.objects.create(session=session, case_id=str(uuid.uuid4()), name=SQLMAP, malicious=True,
                               pattern="CAPEC-66", correlation="marker", started_at=timezone.now(),
                               ended_at=timezone.now(), meta={"scheduled": "3.2"})
    state = session.scenario_state
    state["schedule"][0].update(state="fired", case_id=case.case_id, outcome="held",
                                fired_at=timezone.now().isoformat())
    Session.objects.filter(pk=session.pk).update(scenario_state=state, ended_at=timezone.now())
    alert(session, case.case_id, source="modsecurity", rule="942100")

    told = client.get(f"/api/sessions/{session.pk}/scenario/debrief/").json()
    assert told["timeline"][0]["detected"] is False and told["evidence"] == []

    alert(session, case.case_id, source="suricata", rule="9000101")
    told = client.get(f"/api/sessions/{session.pk}/scenario/debrief/").json()
    assert told["timeline"][0]["detected"] is True
    assert [row["source"] for row in told["evidence"]] == ["suricata"]

DEFAULTS = {"paranoia": 2, "exclusions": []}

@pytest.mark.parametrize("waf, posture, named", [
    ({"paranoia": 3, "exclusions": [], "thresholds": {"inbound": 5, "outbound": 4}}, "untuned", None),
    ({"paranoia": 3, "exclusions": [{"rule_id": 920272, "target": "REQUEST_HEADERS:Referer", "path": ""}],
      "thresholds": {"inbound": 5, "outbound": 4}}, "untuned", "target"),
    ({"paranoia": 3, "exclusions": [], "thresholds": {"inbound": 20000, "outbound": 4}}, "untuned", "threshold"),
    ({"paranoia": 2, "exclusions": [], "thresholds": {"inbound": 10}}, DEFAULTS, "threshold"),
    ({"paranoia": 2, "exclusions": [], "thresholds": {"inbound": 5, "outbound": 4}}, DEFAULTS, None),
], ids=["lowered-to-defaults", "exclusion", "raised-from-untuned", "raised-above-defaults", "at-defaults"])
def test_only_raising_the_thresholds_is_named_a_threshold_fix(waf, posture, named):
    import lesson

    if posture == "untuned":
        posture = wargames.defense("board", "untuned")["waf"]
    assert lesson.fix_class(waf, posture) == named


@pytest.mark.parametrize("given, passes", [
    ("1292", True), ("1,292", True), (" 1,292 ", True), ("1,292,", False), ("12,92", False),
    ("1,2,9,2", False), ("1,29", False), ("1.292", False), ("1,2920", False),
])
def test_a_numeric_answer_takes_thousands_separators_as_kibana_prints_them(given, passes):
    import lesson

    check = {"kind": "answer", "accept": ["1292"]}
    assert lesson.answered(check, given, "lesson.wrong.seen")[0] is passes

def test_an_ordered_answer_still_splits_on_commas():
    import lesson

    check = {"form": "order", "accept": ["1", "292"]}
    assert lesson.answered(check, "1,292", "lesson.wrong.order")[0] is True
