import copy
import json
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.utils import timezone

import scenarios
import wargames
from api import scenario_run
from api.models import Case, CustomerRequest, Detection, Objective, Session
from rules import crs

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TRUTH = json.loads((FIXTURES / "board-auth-users.json").read_text())
DUMPED = (FIXTURES / "sqlmap-orderby-dump.out").read_text()
HELD = (FIXTURES / "sqlmap-not-injectable.out").read_text()
SQLMAP = "board-sqli-orderby-sqlmap"

def declared(**changed):
    one = copy.deepcopy(wargames.scenario_run("2.1"))
    one.update(changed)
    return one

def known():
    return {case["name"]: case["malicious"] for case in wargames.cases("board")}

def checked(one):
    wargames.checked_scenarios([one], known(), "test", tuple(wargames.WARGAMES["board"]["defense"]),
                               {"community", "plain", "readers"})

def opened(scenario_id="2.1", **fields):
    session = Session.objects.create(scenario="board", baseline=dict(TRUTH), course_scenario=scenario_id,
                                     defense=wargames.scenario_run(scenario_id)["defense"], **fields)
    with patch("api.scenario_run.customers.start", lambda session, adapter, body: None), \
            patch("api.scenario_run.ensure_running", lambda: None):
        scenario_run.begin(session, None, wargames.defense("board", session.defense))
    session.refresh_from_db()
    return session

def attacker(output):
    fired = []

    def fire(case, launch, target_url):
        fired.append(case["name"])
        return SimpleNamespace(exit_code=0, output=output)

    return fire, fired

def firing(output):
    fire, fired = attacker(output)
    stack = [
        patch("api.views.harness.fire", fire),
        patch("api.views._origin_for", lambda session, requested: None),
        patch("api.scenario_run._submit", scenario_run.fire_entry),
        patch("api.scenario_run._observe", lambda session, now: None),
    ]
    return stack, fired

class Stack:
    def __init__(self, patches):
        self.patches = patches

    def __enter__(self):
        for one in self.patches:
            one.start()

    def __exit__(self, *exc):
        for one in reversed(self.patches):
            one.stop()

def run_at(session, seconds, output=HELD):
    patches, fired = firing(output)
    now = scenarios.at(session.scenario_state["opened_at"]) + timedelta(seconds=seconds)
    with Stack(patches), patch("api.scenario_run.judge_window", lambda session: None):
        scenario_run.tick(now)
    session.refresh_from_db()
    return fired

def customer(session, at, status=200, marker=None):
    return CustomerRequest.objects.create(
        session=session, marker=marker or str(uuid.uuid4()), action="search-korean", step="search", user="u01",
        origin="kr", source_ip="175.192.0.10", method="GET", path="/search/?q=%EA%B3%B5", status=status, sent_at=at)

def alert(session, marker, source="modsecurity", rule="920272", at=None, src="175.192.0.10"):
    raw = ({"details": {"ruleId": rule}, "request": {"method": "GET", "uri": "/search/?q=%EA%B3%B5"}}
           if source == "modsecurity" else {"alert": {"signature_id": int(rule)}, "http": {"http_method": "GET",
                                                                                          "url": "/?sort=x"}})
    return Detection.objects.create(session=session, detection_id=str(uuid.uuid4()), source=source,
                                    signature=f"rule {rule}", timestamp=at or timezone.now(), src_ip=src,
                                    marker=marker, raw=raw)

def test_the_board_declares_its_two_scenarios_in_order():
    assert [one["id"] for one in wargames.scenarios("board")] == ["1.1", "2.1"]
    assert wargames.scenario_owner("2.1") == "board"
    assert wargames.scenario_owner("9.9") is None

@pytest.mark.parametrize("changed, said", [
    ({"task_class": "speed"}, "task_class"),
    ({"guidance": "half"}, "guidance"),
    ({"minutes": 4, "window_minutes": 4}, "window"),
    ({"defense": "none-such"}, "defense"),
    ({"traffic": {"profile": "nobody", "rate": 1}}, "profile"),
    ({"traffic": {"profile": "readers", "rate": 99}}, "rate"),
    ({"attacks": [{"at": 1200, "case": SQLMAP}]}, "at"),
    ({"attacks": [{"at": 10, "case": "board-normal-search"}]}, "malicious"),
    ({"attacks": []}, "attacks"),
    ({"completion": {"judged": "all"}}, "completion"),
    ({"cards": [{"id": "x", "when": "later"}]}, "cards"),
    ({"hints": ["a", "a"]}, "hints"),
    ({"briefing": {"situation": "x", "goal": "y"}}, "briefing"),
    ({"steps": [{"id": "s", "check": {"kind": "click"}}]}, "worked"),
])
def test_a_scenario_that_breaks_the_descriptor_is_refused(changed, said):
    with pytest.raises(wargames.InvalidCatalogue, match=said):
        checked(declared(**changed))

def test_a_judgement_scenario_must_ask_for_every_item_judged():
    one = copy.deepcopy(wargames.scenario_run("1.1"))
    checked(one)
    with pytest.raises(wargames.InvalidCatalogue, match="completion"):
        checked(dict(one, completion={}))

def test_a_triage_step_names_what_it_waits_for():
    one = copy.deepcopy(wargames.scenario_run("1.1"))
    one["steps"][1]["check"] = {"kind": "triage", "judged": "most"}
    with pytest.raises(wargames.InvalidCatalogue, match="judged"):
        checked(one)

def test_the_catalogue_shows_each_scenario_without_its_attack_schedule(client):
    listed = client.get("/api/wargames/").json()
    board = next(wargame for wargame in listed if wargame["id"] == "board")

    assert [one["id"] for one in board["scenarios"]] == ["1.1", "2.1"]
    shown = json.dumps(board["scenarios"])
    assert "attacks" not in shown and SQLMAP not in shown and '"at"' not in shown
    assert board["scenarios"][1] | {} == board["scenarios"][1]
    assert {key: board["scenarios"][0][key] for key in ("task_class", "guidance", "minutes")} == {
        "task_class": "judgement", "guidance": "worked", "minutes": 15}

def test_opening_a_scenario_takes_its_posture_starts_customers_and_schedules_its_attacks(client):
    started = []
    with patch("api.scenario_run.customers.start", lambda session, adapter, body: started.append(body)), \
            patch("api.scenario_run.ensure_running", lambda: None):
        answer = client.post_json("/api/sessions/", {"scenario": "2.1"})

    assert answer.status_code == 201, answer.content
    session = Session.objects.get(pk=answer.json()["id"])
    state = session.scenario_state
    assert (session.scenario, session.course_scenario, session.defense, answer.json()["kind"]) == (
        "board", "2.1", "level3", "scenario")
    assert started == [{"profile": "readers", "rate": 2}]
    assert [(entry["case"], entry["at"], entry["state"]) for entry in state["schedule"]] == [(SQLMAP, 240, "due")]
    opened_at = scenarios.at(state["opened_at"])
    assert scenarios.at(state["schedule"][0]["due"]) - opened_at == timedelta(seconds=240)
    assert scenarios.at(state["window_at"]) - opened_at == timedelta(minutes=16)

@pytest.mark.parametrize("body", [{"defense": "full"}, {"lesson": "f1"}, {"guidance": True}, {"mode": "self"}])
def test_a_scenario_refuses_settings_it_declares_itself(client, body):
    answer = client.post_json("/api/sessions/", {"scenario": "2.1", **body})

    assert answer.status_code == 400
    assert Session.objects.count() == 0

def test_a_worked_scenario_opens_on_the_step_engine_without_seeding_replays(client):
    with patch("api.scenario_run.customers.start", lambda session, adapter, body: None), \
            patch("api.scenario_run.ensure_running", lambda: None), \
            patch("api.views._seed_logs", lambda session: pytest.fail("a scenario seeds no replays")):
        answer = client.post_json("/api/sessions/", {"scenario": "1.1"})

    detail = client.get(f"/api/sessions/{answer.json()['id']}/").json()
    assert detail["lesson"]["id"] == "1.1"
    assert [step["id"] for step in detail["lesson"]["steps"]] == ["open", "customer", "attack", "all", "done"]
    assert detail["lesson"]["cases"] == [] and "attacks" not in detail["lesson"]
    assert SQLMAP not in json.dumps(detail), "the session's own page names no scheduled attack"

def test_customers_that_cannot_start_close_the_scenario_session(client):
    from range.ports import RangeUnavailable

    def refuse(session, adapter, body):
        raise RangeUnavailable("the users box did not answer")

    with patch("api.scenario_run.customers.start", refuse):
        answer = client.post_json("/api/sessions/", {"scenario": "2.1"})

    assert answer.status_code == 503
    assert Session.objects.get().ended_at is not None

def test_an_attack_fires_only_once_it_is_due():
    session = opened()

    assert run_at(session, 239) == []
    assert run_at(session, 240) == [SQLMAP]
    assert run_at(session, 300) == [], "a fired attack is not fired again"
    entry = session.scenario_state["schedule"][0]
    assert (entry["state"], entry["outcome"]) == ("fired", "held")

def test_a_scheduled_attack_is_the_red_team_s_attempt_not_a_replay():
    session = opened()
    run_at(session, 240)

    case = Case.objects.get(session=session)
    assert case.malicious and case.meta["scheduled"] == "2.1"
    assert not any(case.meta.get(mark) for mark in ("seed", "verify", "check", "replay"))

def test_the_schedule_survives_a_restart_and_resumes_an_interrupted_attack():
    session = opened()
    state = session.scenario_state
    state["schedule"][0]["state"] = scenarios.FIRING
    Session.objects.filter(pk=session.pk).update(scenario_state=state)

    with patch("api.scenario_run.ensure_running", lambda: None):
        scenario_run.resume()
    session.refresh_from_db()
    assert session.scenario_state["schedule"][0]["state"] == scenarios.DUE
    assert run_at(session, 600) == [SQLMAP], "a due attack missed while the platform was down fires on resume"

def test_a_dump_from_a_scheduled_attack_is_credited_as_loot_and_counts_in_the_first_score(client):
    session = opened()
    run_at(session, 240, DUMPED)

    entry = session.scenario_state["schedule"][0]
    assert entry["outcome"] == "leaked" and entry["leaked"] == sorted(TRUTH)
    case = Case.objects.get(session=session)
    assert case.meta["loot"] == sorted(TRUTH)
    assert Objective.objects.filter(session=session).count() > 0
    score = client.get(f"/api/sessions/{session.pk}/score/").json()
    assert score["objectives"]["objectives"] > 0
    assert score["breaches"], "the loss is the red team's, so the first score counts it"

def test_a_held_scheduled_attack_loses_nothing():
    session = opened()
    run_at(session, 240, HELD)

    assert Objective.objects.filter(session=session).count() == 0
    assert session.scenario_state["schedule"][0]["leaked"] == []

def test_an_attack_that_cannot_launch_is_kept_as_failed_with_its_reason():
    from redteam import harness

    session = opened()
    patches, _ = firing(HELD)

    def broken(case, launch, target_url):
        raise harness.ToolUnavailable("sqlmap is not on the attacker box")

    now = scenarios.at(session.scenario_state["opened_at"]) + timedelta(seconds=241)
    with Stack(patches), patch("api.views.harness.fire", broken), \
            patch("api.scenario_run.judge_window", lambda session: None):
        scenario_run.tick(now)
    session.refresh_from_db()
    entry = session.scenario_state["schedule"][0]
    assert entry["state"] == "failed" and "sqlmap" in entry["error"]

def test_closing_cancels_the_attacks_still_to_come(client):
    session = opened()
    with patch("api.views._snapshot_waf", lambda session, **taken: None):
        client.post_json(f"/api/sessions/{session.pk}/close/")

    session.refresh_from_db()
    assert session.scenario_state["schedule"][0]["state"] == "cancelled"
    assert run_at(session, 600) == []

def test_the_learner_s_done_opens_the_window_once(client):
    session = opened()
    answer = client.post_json(f"/api/sessions/{session.pk}/scenario/verify-window/")

    assert answer.status_code == 201, answer.content
    assert answer.json()["phase"] == "window"
    session.refresh_from_db()
    window = session.scenario_state["windows"][0]
    inside = scenarios.inside(session.scenario_state["schedule"], scenarios.at(window["started_at"]),
                              scenarios.at(window["ends_at"]))
    assert window["by"] == "learner" and [entry["case"] for entry in inside] == [SQLMAP]
    assert client.post_json(f"/api/sessions/{session.pk}/scenario/verify-window/").status_code == 409

def test_the_window_fires_every_attack_variant_at_least_once_inside_it():
    session = opened()
    run_at(session, 240)
    begun = scenarios.at(session.scenario_state["opened_at"]) + timedelta(seconds=300)
    scenario_run.start_window(session, "learner", begun)

    session.refresh_from_db()
    added = session.scenario_state["schedule"][1]
    assert (added["case"], added["in_window"], added["state"]) == (SQLMAP, True, "due")
    assert scenarios.at(added["due"]) == begun + timedelta(minutes=2)

def test_an_attack_already_due_inside_the_window_is_not_doubled():
    session = opened()
    begun = scenarios.at(session.scenario_state["opened_at"]) + timedelta(seconds=60)
    scenario_run.start_window(session, "learner", begun)

    session.refresh_from_db()
    assert len(session.scenario_state["schedule"]) == 1

def test_the_window_starts_by_itself_at_its_scheduled_time():
    session = opened()
    run_at(session, 16 * 60)

    assert session.scenario_state["windows"][0]["by"] == "schedule"

def window_judged(session, blocked_inside=0, blocked_outside=0, output=HELD):
    begun = scenarios.at(session.scenario_state["opened_at"]) + timedelta(seconds=300)
    scenario_run.start_window(session, "learner", begun)
    session.refresh_from_db()
    window = session.scenario_state["windows"][-1]
    start, end = scenarios.at(window["started_at"]), scenarios.at(window["ends_at"])
    for _ in range(blocked_inside):
        customer(session, start + timedelta(seconds=30), status=403)
    for _ in range(blocked_outside):
        customer(session, start - timedelta(seconds=30), status=403)
    customer(session, start + timedelta(seconds=40), status=200)
    patches, _ = firing(output)
    run_at(session, 299, output)
    with Stack(patches), patch("api.scenario_run.customers.refresh", lambda session, adapter: None), \
            patch("api.views._snapshot_waf", lambda session, **taken: None):
        scenario_run.tick(end + timedelta(seconds=1))
    session.refresh_from_db()
    return session.scenario_state["windows"][-1]["result"]

def test_the_window_passes_when_every_customer_is_served_and_every_attack_held():
    session = opened()

    result = window_judged(session, blocked_outside=3)

    assert result["passed"] is True, result
    assert (result["attacks"], result["held"], result["customers_blocked"]) == (1, 1, 0)

def test_one_customer_blocked_inside_the_window_fails_it():
    result = window_judged(opened(), blocked_inside=1)

    assert result["passed"] is False
    assert ["scenario.fail.blocked", [1]] in result["reasons"]

def test_an_attack_that_leaks_inside_the_window_fails_it():
    result = window_judged(opened(), output=DUMPED)

    assert result["passed"] is False
    assert ["scenario.fail.leaked", [1, 1]] in result["reasons"]

def test_the_window_waits_for_its_attacks_before_it_is_judged():
    session = opened()
    scenario_run.start_window(session, "learner")
    session.refresh_from_db()
    window = session.scenario_state["windows"][-1]
    state = session.scenario_state
    for entry in state["schedule"]:
        entry["state"] = scenarios.FIRING
    Session.objects.filter(pk=session.pk).update(scenario_state=state)

    with patch("api.scenario_run._observe", lambda session, now: None):
        scenario_run.tick(scenarios.at(window["ends_at"]) + timedelta(seconds=5))
    session.refresh_from_db()
    assert session.scenario_state["windows"][-1]["result"] is None

def test_a_failed_window_can_be_followed_by_another(client):
    session = opened()
    window_judged(session, blocked_inside=1)

    assert client.post_json(f"/api/sessions/{session.pk}/scenario/verify-window/").status_code == 201

def test_a_judgement_window_needs_every_earlier_item_judged_right():
    session = opened("1.1")
    marker = str(uuid.uuid4())
    customer(session, timezone.now() - timedelta(minutes=2), status=403, marker=marker)
    alert(session, marker, at=timezone.now() - timedelta(minutes=2))

    result = window_judged(session)

    assert ["scenario.fail.judged", [0, 1]] in result["reasons"]

def test_triage_lists_what_a_defender_sees_and_no_label(client):
    session = opened("1.1")
    blocked = str(uuid.uuid4())
    customer(session, timezone.now(), status=403, marker=blocked)
    alert(session, blocked, rule="920272")
    alert(session, blocked, rule="949110")
    case = Case.objects.create(session=session, case_id=str(uuid.uuid4()), name=SQLMAP, malicious=True,
                               correlation="marker", started_at=timezone.now(), ended_at=timezone.now(),
                               meta={"scheduled": "1.1"})
    for _ in range(3):
        alert(session, case.case_id, source="suricata", rule="9000001", src="5.188.10.10")

    listed = client.get(f"/api/sessions/{session.pk}/triage/").json()

    assert listed["total"] == 2
    shown = json.dumps(listed)
    for leak in (blocked, case.case_id, SQLMAP, "malicious", "search-korean", "customer"):
        assert leak not in shown
    by_waf = {item["waf"]: item for item in listed["items"]}
    assert by_waf["blocked"]["status"] == 403 and by_waf["blocked"]["sources"] == ["175.192.0.10"]
    assert {rule["rule"] for rule in by_waf["blocked"]["rules"]} == {"920272", "949110"}
    assert by_waf["none"]["alerts"] == 3 and by_waf["none"]["request"] == {"method": "GET", "path": "/?sort=x"}

def test_triage_leaves_out_replays_and_the_learner_s_own_browsing(client):
    session = opened("1.1")
    replay = Case.objects.create(session=session, case_id=str(uuid.uuid4()), name=SQLMAP, malicious=True,
                                 correlation="marker", started_at=timezone.now(), ended_at=timezone.now(),
                                 meta={"replay": True})
    alert(session, replay.case_id)
    alert(session, session.browse_marker)

    assert client.get(f"/api/sessions/{session.pk}/triage/").json()["total"] == 0

def judging(client, session, item, verdict, succeeded=None):
    return client.post_json(f"/api/sessions/{session.pk}/triage/",
                            {"item": item, "verdict": verdict, **({} if succeeded is None else {"succeeded": succeeded})})

def test_a_verdict_is_judged_against_the_record_and_success_against_the_target(client):
    session = opened("1.1")
    leaked = Case.objects.create(session=session, case_id=str(uuid.uuid4()), name=SQLMAP, malicious=True,
                                 correlation="marker", started_at=timezone.now(), ended_at=timezone.now(),
                                 meta={"scheduled": "1.1", "loot": ["admin"]})
    alert(session, leaked.case_id, source="suricata", rule="9000001")
    blocked = str(uuid.uuid4())
    customer(session, timezone.now(), status=403, marker=blocked)
    alert(session, blocked)
    items = {item["waf"]: item["item"] for item in client.get(f"/api/sessions/{session.pk}/triage/").json()["items"]}

    held_guess = judging(client, session, items["none"], "attack", False).json()
    assert (held_guess["right"], held_guess["verdict_right"], held_guess["succeeded_right"]) == (False, True, False)
    assert judging(client, session, items["none"], "attack", True).json()["right"] is True
    assert judging(client, session, items["logged"], "customer").json()["right"] is True
    assert judging(client, session, items["logged"], "attack", False).json()["right"] is False

    session.refresh_from_db()
    kept = session.scenario_state["triage"][items["none"]]
    assert (kept["tries"], kept["first_right"], kept["right"]) == (2, False, True)

@pytest.mark.parametrize("body", [
    {"verdict": "attack"},
    {"verdict": "maybe", "succeeded": False},
    {"verdict": "customer", "item": "no-such-item"},
])
def test_a_verdict_that_cannot_be_judged_is_refused(client, body):
    session = opened("1.1")
    marker = str(uuid.uuid4())
    customer(session, timezone.now(), status=403, marker=marker)
    alert(session, marker)
    item = client.get(f"/api/sessions/{session.pk}/triage/").json()["items"][0]["item"]

    assert client.post_json(f"/api/sessions/{session.pk}/triage/", {"item": item, **body}).status_code == 400

def test_a_triage_step_passes_on_the_learner_s_right_verdicts(client):
    session = opened("1.1", guidance=True, lesson="1.1")
    marker = str(uuid.uuid4())
    customer(session, timezone.now(), status=403, marker=marker)
    alert(session, marker)
    item = client.get(f"/api/sessions/{session.pk}/triage/").json()["items"][0]["item"]
    check = lambda step: client.post_json(f"/api/sessions/{session.pk}/lesson/steps/{step}/check/",
                                          {"poll": True}).json()["passed"]

    assert check("customer") is False
    judging(client, session, item, "customer")
    assert (check("customer"), check("attack"), check("all")) == (True, False, True)

def test_a_verdict_wrong_twice_on_one_item_offers_a_hint_without_recording_one(client):
    session = opened("1.1")
    marker = str(uuid.uuid4())
    customer(session, timezone.now(), status=403, marker=marker)
    alert(session, marker)
    item = client.get(f"/api/sessions/{session.pk}/triage/").json()["items"][0]["item"]

    judging(client, session, item, "attack", False)
    assert client.get(f"/api/sessions/{session.pk}/scenario/").json()["hints"]["offer"] is None
    judging(client, session, item, "attack", True)

    status = client.get(f"/api/sessions/{session.pk}/scenario/").json()
    assert status["hints"]["offer"]["reason"] == "triage"
    session.refresh_from_db()
    assert session.hints == [], "an offered hint is recorded only when it is opened"

def test_a_failing_step_check_twice_offers_a_hint_in_a_scenario_instead_of_recording_it(client):
    session = opened("1.1", guidance=True, lesson="1.1")
    for _ in range(2):
        client.post_json(f"/api/sessions/{session.pk}/lesson/steps/all/check/", {})

    session.refresh_from_db()
    assert session.scenario_state["offer"]["reason"] == "check"
    assert session.hints == []
    assert session.lesson_steps["all"].get("hint", 0) == 0

def test_the_same_waf_change_applied_again_offers_a_hint(client):
    from tests.test_lesson_api import Stand

    session = opened(waf={"paranoia": 3, "exclusions": []})
    tuning = {"paranoia": 3, "exclusions": [{"rule_id": 920272, "target": "ARGS:q", "path": "/search/"}]}
    with patch("range.docker.Docker.runner", Stand().runner()):
        client.put(f"/api/sessions/{session.pk}/waf/", json.dumps(tuning), content_type="application/json")
        session.refresh_from_db()
        assert session.scenario_state["offer"] is None
        client.put(f"/api/sessions/{session.pk}/waf/", json.dumps(tuning), content_type="application/json")

    session.refresh_from_db()
    assert session.scenario_state["offer"]["reason"] == "waf"
    assert len(session.scenario_state["waf"]) == 2

def test_five_minutes_without_a_change_while_customers_are_blocked_offers_a_hint():
    session = opened()
    now = timezone.now()
    later = scenarios.at(session.scenario_state["last_change"]) + timedelta(minutes=5, seconds=1)
    customer(session, later - timedelta(minutes=1), status=403)

    posture = {"file": crs.rendered(crs.checked(wargames.defense("board", "level3")["waf"]))}
    with patch("api.scenario_run.customers.refresh", lambda session, adapter: None), \
            patch("api.views._ingest", lambda session, within=None: {}), \
            patch("api.views._waf_read", lambda session: posture):
        scenario_run._observe(session, now + timedelta(minutes=4))
        session.refresh_from_db()
        assert session.scenario_state["offer"] is None
        scenario_run._observe(session, later)

    session.refresh_from_db()
    assert session.scenario_state["offer"]["reason"] == "idle"

def test_quiet_customers_never_count_as_stuck():
    session = opened()
    later = scenarios.at(session.scenario_state["last_change"]) + timedelta(minutes=9)

    with patch("api.scenario_run.customers.refresh", lambda session, adapter: None), \
            patch("api.views._ingest", lambda session, within=None: {}), \
            patch("api.views._waf_read", lambda session: {"file": ""}):
        scenario_run._observe(session, later)

    session.refresh_from_db()
    assert session.scenario_state["offer"] is None

def test_opening_a_hint_records_it_and_clears_the_offer(client):
    session = opened()
    scenario_run.stuck(session, "idle", "")

    opened_hint = client.post_json(f"/api/sessions/{session.pk}/scenario/hints/").json()

    assert (opened_hint["hint"], opened_hint["text"], opened_hint["reason"]) == ("find", "scenario.korean.hint.find",
                                                                               "idle")
    session.refresh_from_db()
    assert session.scenario_state["offer"] is None
    assert session.hints == [{"hint": "find", "level": "hint", "reason": "idle",
                              "at": session.scenario_state["hints"][0]["at"]}]
    for _ in range(3):
        client.post_json(f"/api/sessions/{session.pk}/scenario/hints/")
    assert client.post_json(f"/api/sessions/{session.pk}/scenario/hints/").status_code == 409

def test_the_status_counts_the_last_minute_one_alerted_request_per_marker_and_hides_the_schedule(client):
    session = opened()
    now = timezone.now()
    customer(session, now - timedelta(seconds=20), status=403)
    customer(session, now - timedelta(minutes=3), status=403)
    customer(session, now - timedelta(seconds=10), status=200)
    alert(session, "sqlmap-run", at=now - timedelta(seconds=5))
    alert(session, "sqlmap-run", at=now - timedelta(seconds=4), rule="942100")
    alert(session, "a-customer", at=now - timedelta(seconds=3))
    alert(session, None, at=now - timedelta(seconds=2))
    alert(session, "earlier", at=now - timedelta(minutes=5))

    status = client.get(f"/api/sessions/{session.pk}/scenario/").json()

    assert status["live"]["customers_blocked_per_minute"] == 1
    assert status["live"]["alerted_per_minute"] == 2
    assert status["live"]["customers"] == {"sent": 3, "served": 1, "blocked": 2}
    assert (status["phase"], status["completion"]["state"]) == ("running", "pending")
    assert set(status["cards"]) == {"blocked", "narrow"}
    assert SQLMAP not in json.dumps(status) and "schedule" not in status

def test_the_debrief_stays_closed_until_the_window_is_judged_then_shows_the_timeline(client):
    session = opened()
    assert client.get(f"/api/sessions/{session.pk}/scenario/debrief/").status_code == 409

    run_at(session, 240)
    window_judged(session, blocked_outside=2)
    told = client.get(f"/api/sessions/{session.pk}/scenario/debrief/").json()

    assert told["overview"]["passed"] is True and told["overview"]["verified"] == 1
    assert [(entry["case"], entry["in_window"], entry["outcome"]) for entry in told["timeline"]] == [
        (SQLMAP, False, "held"), (SQLMAP, True, "held")]
    assert told["customers"]["blocked"] == 2 and told["customers"]["in_window"] == [0]
    assert told["cases"] == [{"name": SQLMAP, "malicious": True, "before": "held", "after": "held"}]

def test_a_put_without_thresholds_keeps_the_thresholds_in_force(client):
    from tests.test_lesson_api import Stand

    session = Session.objects.create(scenario="board", baseline=dict(TRUTH))
    raised = {"paranoia": 3, "exclusions": [], "thresholds": {"inbound": 10000, "outbound": 10000}}
    with patch("range.docker.Docker.runner", Stand().runner()):
        client.put(f"/api/sessions/{session.pk}/waf/", json.dumps(raised), content_type="application/json")
        read = client.put(f"/api/sessions/{session.pk}/waf/", json.dumps({"paranoia": 2}),
                          content_type="application/json").json()
        cleared = client.put(f"/api/sessions/{session.pk}/waf/", json.dumps({"paranoia": 2, "thresholds": None}),
                             content_type="application/json").json()

    assert (read["paranoia"], read["thresholds"]) == (2, {"inbound": 10000, "outbound": 10000})
    assert "thresholds" not in cleared

def test_the_raw_uri_exclusion_reads_back_through_the_api(client):
    from tests.test_lesson_api import Stand

    session = Session.objects.create(scenario="board", baseline=dict(TRUTH))
    tuning = {"paranoia": 3, "exclusions": [{"rule_id": 920272, "target": "REQUEST_URI_RAW", "path": "/search/"}]}
    with patch("range.docker.Docker.runner", Stand().runner()):
        client.put(f"/api/sessions/{session.pk}/waf/", json.dumps(tuning), content_type="application/json")
        read = client.get(f"/api/sessions/{session.pk}/waf/").json()

    assert read["exclusions"] == tuning["exclusions"]
    assert read["file"] == crs.rendered(tuning)

def test_the_score_reads_customer_records_before_it_sets_their_alerts_apart(client):
    session = Session.objects.create(scenario="board", baseline=dict(TRUTH), traffic={"running": True})
    pulled = []
    with patch("api.views.customers.refresh", lambda session, adapter: pulled.append(session.pk)):
        client.get(f"/api/sessions/{session.pk}/score/")

    assert pulled == [session.pk]

def test_a_new_waf_change_the_engine_happened_to_read_first_is_not_called_applied_again(client):
    from tests.test_lesson_api import Stand

    session = opened(waf={"paranoia": 3, "exclusions": []})
    first = {"paranoia": 3, "exclusions": [{"rule_id": 920272, "target": "ARGS:q", "path": "/search/"}]}
    second = {"paranoia": 3, "exclusions": [{"rule_id": 949110}]}
    put = lambda tuning: client.put(f"/api/sessions/{session.pk}/waf/", json.dumps(tuning),
                                    content_type="application/json")
    with patch("range.docker.Docker.runner", Stand().runner()):
        put(first)
        scenario_run._waf_seen(session, crs.rendered(crs.checked(second)), timezone.now())
        put(second)
        session.refresh_from_db()
        assert session.scenario_state["offer"] is None
        put(second)

    session.refresh_from_db()
    assert session.scenario_state["offer"]["reason"] == "waf"

def test_a_judgement_window_is_judged_on_the_verdicts_and_reports_blocked_customers_beside_them():
    session = opened("1.1")
    marker = str(uuid.uuid4())
    customer(session, timezone.now() - timedelta(minutes=2), status=403, marker=marker)
    alert(session, marker, at=timezone.now() - timedelta(minutes=2))
    item = scenario_run._items(session)[0]["item"]
    scenario_run._update(session.pk, lambda state, held: state["triage"].update(
        {item: {"verdict": "customer", "succeeded": None, "right": True, "tries": 1, "wrong": 0, "first_right": True,
                "at": "x"}}))
    session.refresh_from_db()

    result = window_judged(session, blocked_inside=2)

    assert result["passed"] is True, result
    assert result["customers_blocked"] == 2

def test_an_availability_scenario_must_ask_for_customers_served_and_attacks_held():
    with pytest.raises(wargames.InvalidCatalogue, match="completion"):
        checked(declared(completion={"served": "all"}))
