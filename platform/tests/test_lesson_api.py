import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.utils import timezone

import wargames
from api.models import Case, Detection, Objective, Session
from range.ports import Ran
from rules import crs

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
TRUTH = json.loads((FIXTURES / "board-auth-users.json").read_text())
SEEDED = ["board-normal-search"]
DUMPED = (FIXTURES / "sqlmap-orderby-dump.out").read_text()
HELD = (FIXTURES / "sqlmap-not-injectable.out").read_text()

class Stand:
    def __init__(self):
        self.calls = []
        self.files = {}

    def runner(self):
        calls, files = self.calls, self.files

        def runner(adapter, role, segment_id=""):
            def run(argv, stdin=None, timeout=60.0):
                calls.append((adapter.session, role, " ".join(argv), stdin))
                if " ".join(argv).endswith(crs.workers_of(crs.Layout().pid)):
                    return Ran(0, str(len(calls)))
                if " ".join(argv).endswith("cat > " + crs.EXCLUSIONS):
                    files[(adapter.session, role)] = stdin
                if crs.EXCLUSIONS + " 2>/dev/null" in " ".join(argv):
                    return Ran(0, files.get((adapter.session, role), ""))
                if "reload-rules" in argv:
                    return Ran(0, '{"message":"done","return":"OK"}')
                return Ran(0, "")
            return run

        return runner

    def to(self, role):
        return [call for call in self.calls if call[1] == role]

def attacker(outputs):
    fired = []

    def fire(case, launch, target_url):
        fired.append(case["name"])
        return SimpleNamespace(exit_code=0, output=outputs.get(case["name"], "http_code=200\n"))

    return fire, fired

def board(**fields):
    return Session.objects.create(scenario="board", baseline=dict(TRUTH), **fields)

def foundation(lesson_id, **fields):
    return board(guidance=True, lesson=lesson_id, defense=wargames.lesson_defense("board", lesson_id), **fields)

def step(client, session, step_id, tail="check/", body=None):
    return client.post_json(f"/api/sessions/{session.pk}/lesson/steps/{step_id}/{tail}", body or {})

def put(client, session_id, tuning):
    return client.put(
        f"/api/sessions/{session_id}/waf/", json.dumps(tuning), content_type="application/json",
    )

@pytest.mark.parametrize("body, refused", [
    ({"defense": "none-such"}, "none-such"),
    ({"defense": ["full"]}, "full"),
    ({"guidance": "yes"}, "guidance"),
    ({"scenario": "corp", "guidance": True}, "no lesson"),
    ({"scenario": "corp", "defense": "minimal"}, "minimal"),
    ({"lesson": "no-such-lesson"}, "no-such-lesson"),
    ({"lesson": "waf-exclusion"}, "waf-exclusion"),
    ({"lesson": "3.1"}, "3.1"),
    ({"lesson": "f1", "guidance": False}, "guidance"),
    ({"scenario": "corp", "lesson": "f1"}, "no lesson"),
])
def test_settings_the_scenario_does_not_declare_are_refused(client, body, refused):
    answer = client.post_json("/api/sessions/", body)

    assert answer.status_code == 400, answer.content
    assert refused in answer.json()["detail"]
    assert Session.objects.count() == 0

@pytest.mark.takes_defense
def test_the_chosen_defense_is_applied_to_the_session_s_own_stack_after_it_is_up(client):
    stand, order = Stand(), []
    with patch("range.docker.Docker.runner", stand.runner()), \
            patch("range.docker.Docker.open_session",
                  lambda self, session_id, live=(): order.append(len(stand.calls))):
        opened = client.post_json("/api/sessions/", {"defense": "minimal"}).json()

    session = Session.objects.get(pk=opened["id"])
    rules = (ROOT / "deploy/suricata/rules/local.rules").read_text()
    seeded = [call for call in stand.to("sensor") if call[3] is not None]
    written = [call for call in stand.to("gateway") if call[3] is not None]
    assert order == [0], "the defense was written before the session's stack was up"
    assert seeded and seeded[0][0] == session.pk and seeded[0][3] == rules
    assert written and "tx.blocking_paranoia_level=4" in written[0][3]
    assert session.waf == {"paranoia": 4, "exclusions": []}

@pytest.mark.takes_defense
def test_a_scenario_without_a_defense_gets_the_default_rules_and_an_untouched_waf(client):
    stand = Stand()
    with patch("range.docker.Docker.runner", stand.runner()):
        answer = client.post_json("/api/sessions/", {"scenario": "corp"})

    rules = (ROOT / "deploy/suricata/rules/local.rules").read_text()
    seeded = [call for call in stand.to("sensor") if call[3] is not None]
    assert answer.status_code == 201, answer.content
    assert [call[3] for call in seeded] == [rules], (
        "no session's sensor shares a rules mount any more, so one that is not "
        "seeded at open runs with no rules and raises no alert"
    )
    assert stand.to("gateway") == []

def test_the_waf_tuning_round_trips_through_the_api(client):
    session = board(waf={"paranoia": 4, "exclusions": []})
    tuning = {"paranoia": 4, "exclusions": [
        {"rule_id": 920273, "target": "ARGS:q", "path": "/search/"},
    ]}
    with patch("range.docker.Docker.runner", Stand().runner()):
        answer = put(client, session.pk, tuning)
        read = client.get(f"/api/sessions/{session.pk}/waf/").json()

    assert answer.status_code == 200, answer.content
    assert {k: read[k] for k in ("paranoia", "exclusions")} == tuning
    assert read["file"] == crs.rendered(tuning)
    assert read["version"] == answer.json()["version"]

def test_the_waf_api_reports_what_is_in_the_waf_s_file_after_an_edit_in_the_terminal(client):
    session = board(waf={"paranoia": 4, "exclusions": []})
    stand = Stand()
    edited = crs.rendered({"paranoia": 4, "exclusions": []}) + (
        "# SecRule REQUEST_FILENAME \"@beginsWith /old/\" \"id:10009,ctl:ruleRemoveById=942100\"\n"
        "SecRule REQUEST_FILENAME \"@beginsWith /search/\" \\\n"
        "    \"id:10001,phase:1,pass,nolog,ctl:ruleRemoveTargetById=920273;ARGS:q\"\n"
    )
    stand.files[(session.pk, "gateway")] = edited
    with patch("range.docker.Docker.runner", stand.runner()):
        read = client.get(f"/api/sessions/{session.pk}/waf/").json()

    assert read["paranoia"] == 4
    assert read["exclusions"] == [{"rule_id": 920273, "target": "ARGS:q", "path": "/search/"}], (
        "a commented-out line is not in force; a continued line is"
    )
    assert read["file"] == edited

def test_a_tuning_goes_only_to_the_gateway_of_the_session_asked(client):
    first, second = board(), board()
    stand = Stand()
    with patch("range.docker.Docker.runner", stand.runner()):
        put(client, second.pk, {"paranoia": 3})

    assert {(session, role) for session, role, _, _ in stand.calls} == {(second.pk, "gateway")}
    assert Session.objects.get(pk=first.pk).waf is None

def test_a_closed_session_takes_no_tuning(client):
    session = board()
    client.post_json(f"/api/sessions/{session.pk}/close/")
    stand = Stand()
    with patch("range.docker.Docker.runner", stand.runner()):
        answer = put(client, session.pk, {"paranoia": 3})

    assert answer.status_code == 409
    assert stand.calls == []

def test_a_tuning_that_would_inject_configuration_is_refused_with_the_reason(client):
    session = board()
    stand = Stand()
    with patch("range.docker.Docker.runner", stand.runner()):
        answer = put(client, session.pk, {"paranoia": 4, "exclusions": [
            {"rule_id": 920273, "target": 'ARGS:q"\nSecRuleEngine Off'},
        ]})

    assert answer.status_code == 400
    assert "target" in answer.json()["detail"]
    assert stand.calls == []

def test_a_tuning_nginx_refuses_is_reported_and_not_saved(client):
    session = board(waf={"paranoia": 4, "exclusions": []})

    def runner(adapter, role, segment_id=""):
        return lambda argv, stdin=None, timeout=60.0: Ran(
            1 if "nginx" in " ".join(argv) else 0, "nginx: [emerg] Rules error",
        )

    with patch("range.docker.Docker.runner", runner):
        answer = put(client, session.pk, {"paranoia": 1})

    assert answer.status_code == 400 and "Rules error" in answer.json()["detail"]
    assert Session.objects.get(pk=session.pk).waf == {"paranoia": 4, "exclusions": []}

def red_submits_the_dump(client, session):
    rows = [{"username": name, "hash": digest} for name, digest in TRUTH.items()]
    answer = client.post_json(f"/api/sessions/{session.pk}/loot/", {"loot": rows})
    assert answer.status_code == 200, answer.content
    return answer.json()

def red_fires(client, session, name="board-sqli-orderby-sqlmap", output=HELD):
    fire, _ = attacker({name: output})
    with patch("api.views.harness.fire", fire):
        answer = client.post_json(f"/api/sessions/{session.pk}/attacks/", {"case": name})
    assert answer.status_code == 201, answer.content
    return answer.json()

def old_replays(session):
    at = timezone.now()
    for mark, name, malicious, meta in (
        ("verify", "board-sqli-orderby-sqlmap", True, {"verify": "run-1", "leaked": sorted(TRUTH), "outcome": "leaked"}),
        ("check", "board-sqli-orderby-sqlmap-tamper", True, {"check": "write", "status": 403}),
        ("replay", "board-normal-search", False, {"replay": True, "status": 200, "outcome": "served"}),
    ):
        Case.objects.create(session=session, case_id=f"old-{mark}", name=name, malicious=malicious,
                            correlation="marker", started_at=at - timedelta(seconds=30),
                            ended_at=at - timedelta(seconds=5), meta=meta)
        Detection.objects.create(session=session, detection_id=f"alert-{mark}", source="modsecurity",
                                 signature="942100" if malicious else "920273",
                                 timestamp=at - timedelta(seconds=20), marker=f"old-{mark}")

def test_close_snapshots_the_waf_the_learner_left_and_a_closed_session_reports_that_config(client):
    session = board(waf={"paranoia": 4, "exclusions": []})
    stand = Stand()
    tuned = {"paranoia": 4, "exclusions": [{"rule_id": 920273, "target": "ARGS:q", "path": "/search/"}]}
    stand.files[(session.pk, "gateway")] = crs.rendered(tuned)
    with patch("range.docker.Docker.runner", stand.runner()):
        client.post_json(f"/api/sessions/{session.pk}/close/")
    after = Stand()
    with patch("range.docker.Docker.runner", after.runner()):
        read = client.get(f"/api/sessions/{session.pk}/waf/").json()

    assert after.to("gateway") == [], "a closed session's WAF is read from its record, not the slot's next tenant"
    snapshot = Session.objects.get(pk=session.pk).waf_snapshots[0]
    assert snapshot["closed"] is True
    assert {k: snapshot["waf"][k] for k in ("paranoia", "exclusions", "file")} == tuned | {"file": crs.rendered(tuned)}
    assert {k: read[k] for k in ("paranoia", "exclusions", "file")} == tuned | {"file": crs.rendered(tuned)}, (
        "after close the learner's last configuration, not the one the session opened with"
    )

def test_close_snapshots_the_waf_before_the_slot_is_rebuilt_and_an_unreadable_waf_does_not_stop_it(client):
    stand, order = Stand(), []
    tuned = {"paranoia": 3, "exclusions": []}

    class Rebuilt(OneSlot):
        def rebuild_slot(self):
            order.append(len(stand.to("gateway")))
            return []

    session = board(waf={"paranoia": 4, "exclusions": []})
    stand.files[("slot-1", "gateway")] = crs.rendered(tuned)
    with patch("api.views.substrate", lambda: Rebuilt(stand)):
        closed = client.post_json(f"/api/sessions/{session.pk}/close/")
    unreadable = board(waf={"paranoia": 2, "exclusions": []})
    left = client.post_json(f"/api/sessions/{unreadable.pk}/close/")

    assert closed.status_code == left.status_code == 200
    assert order == [1], "the configuration is read before the rebuild wipes it"
    assert Session.objects.get(pk=session.pk).waf_snapshots[0]["closed"] is True
    assert client.get(f"/api/sessions/{session.pk}/waf/").json()["paranoia"] == 3
    assert Session.objects.get(pk=unreadable.pk).ended_at is not None
    assert client.get(f"/api/sessions/{unreadable.pk}/waf/").json()["paranoia"] == 2

class OneSlot:
    session = "slot-1"
    slots = max_sessions = 1

    def __init__(self, stand):
        self.runner = stand.runner().__get__(self)

    def in_slot(self, number):
        return self

    def segments(self):
        return ()

    def launcher(self, segment_id):
        return lambda image, argv, timeout=600.0: Ran(0, "")

@pytest.mark.takes_defense
def test_a_guided_open_on_a_slotted_range_takes_the_lesson_posture_and_seeds_the_logs(client):
    stand = Stand()
    fire, fired = attacker({})
    with patch("api.views.substrate", lambda: OneSlot(stand)), patch("api.views.harness.fire", fire):
        answer = client.post_json("/api/sessions/", {"guidance": True, "defense": "minimal"})

    assert answer.status_code == 201, answer.content
    session = Session.objects.get(pk=answer.json()["id"])
    written = [call for call in stand.to("gateway") if call[3] is not None]
    assert written and "tx.blocking_paranoia_level=4" in written[0][3], "the lesson opened at the WAF's own level"
    assert session.waf == {"paranoia": 4, "exclusions": []}
    assert fired == SEEDED and all(case.meta.get("seed") for case in session.cases.all())
    assert stand.to("sensor") == [], (
        "the slot was offered only once its sensors held the baseline rules, so the open leaves them alone"
    )

def test_a_guided_open_that_names_no_defense_takes_the_one_its_lesson_declares(client):
    fire, _ = attacker({})
    with patch("api.views.harness.fire", fire):
        guided = client.post_json("/api/sessions/", {"lesson": "f6"}).json()
        client.post_json(f"/api/sessions/{guided['id']}/close/")
        plain = client.post_json("/api/sessions/", {}).json()

    assert (guided["defense"], plain["defense"]) == ("missed", "full")

def test_a_replayed_request_records_the_status_the_target_answered_with(client):
    session = board()
    fire, _ = attacker({"board-normal-search-with-apostrophe": "http_code=403\n"})
    with patch("api.views.harness.fire", fire):
        answer = client.post_json(
            f"/api/sessions/{session.pk}/attacks/", {"case": "board-normal-search-with-apostrophe"},
        )

    assert answer.json()["meta"]["status"] == 403
    assert "blocked" not in answer.json()["meta"], (
        "outside the lesson a block is not judged from the target's records, so it is not claimed"
    )

def test_a_foundation_s_seed_cases_are_kept_out_of_both_scores(client):
    fire, _ = attacker({"board-normal-search": "http_code=403\n"})
    with patch("api.views.harness.fire", fire):
        opened = client.post_json("/api/sessions/", {"guidance": True}).json()
    session = Session.objects.get(pk=opened["id"])
    seeded = Case.objects.get(session=session)
    Detection.objects.create(session=session, detection_id="d1", source="modsecurity",
                             signature="920273", timestamp=timezone.now(), marker=seeded.case_id)

    score = client.get(f"/api/sessions/{session.pk}/score/").json()

    assert {mark: seeded.meta[mark] for mark in ("seed", "status", "blocked")} == {
        "seed": True, "status": 403, "blocked": True}
    assert (score["tp"], score["fp"], score["fn"], score["tn"]) == (0, 0, 0, 0)
    assert score["unattributed"] == 0, "an alert drawn by a seed is not an orphan"
    assert score["objectives"]["objectives"] == 0

def test_old_lesson_replays_are_left_out_of_both_scores_and_loot_a_red_player_submits_still_counts(client):
    session = board(guidance=True, lesson="waf-exclusion")
    old_replays(session)
    before = client.get(f"/api/sessions/{session.pk}/score/").json()
    red_submits_the_dump(client, session)
    client.post_json(f"/api/sessions/{session.pk}/close/")

    score = client.get(f"/api/sessions/{session.pk}/score/").json()

    assert (score["tp"], score["fp"], score["fn"], score["tn"]) == (0, 0, 0, 0)
    assert score["unattributed"] == 0, "an alert drawn by a lesson replay is not an orphan"
    assert before["objectives"]["objectives"] == 0, "a replay's own leak is kept out of the first score"
    assert score["objectives"]["objectives"] == 3, (
        "loot a red player submits, matched against the snapshot, is still a lost objective"
    )
    assert score["objectives"]["undetected"] == 3

def test_a_guided_open_whose_replay_cannot_run_is_refused_as_unavailable(client):
    from redteam.tools import ToolUnavailable

    def fire(case, launch, target_url):
        raise ToolUnavailable("sqlmap: the tool did not run")

    with patch("api.views.harness.fire", fire):
        answer = client.post_json("/api/sessions/", {"guidance": True})

    assert answer.status_code == 503
    assert Session.objects.get().ended_at is not None, (
        "the half-open session is closed, so the next open takes its stack down"
    )

def test_a_session_says_whether_it_is_a_lesson_and_that_it_is_ready_only_once_it_has_opened(client):
    fire, _ = attacker({})
    with patch("api.views.harness.fire", fire):
        opened = client.post_json("/api/sessions/", {"guidance": True}).json()
    opening = Session.objects.create(scenario="board", baseline=[])

    listed = {row["id"]: row for row in client.get("/api/sessions/?state=open").json()}

    assert (opened["kind"], opened["ready"]) == ("lesson", True)
    assert (listed[opening.pk]["kind"], listed[opening.pk]["ready"]) == ("wargame", False), (
        "a session whose open has not finished is still being prepared"
    )
    assert "result" not in listed[opening.pk], "an open row in the list is not judged"

def test_a_finished_session_reports_the_objectives_it_lost_and_how_many_went_unseen(client):
    session = board()
    red_fires(client, session, output=DUMPED)
    red_submits_the_dump(client, session)
    client.post_json(f"/api/sessions/{session.pk}/close/")

    detail = client.get(f"/api/sessions/{session.pk}/").json()

    assert detail["result"]["objectives"] == {"lost": 3, "undetected": 3, "total": 3}
    assert detail["result"] == {"objectives": detail["result"]["objectives"], "scenario": None}

def test_hints_are_recorded_on_the_session_and_read_back_after_close_and_do_is_no_level(client):
    session = foundation("f1")
    hints = f"/api/sessions/{session.pk}/lesson/hints/"

    second = [client.post_json(hints, {"step": "entry", "level": "hint"}).json() for _ in range(2)][-1]
    third = client.post_json(hints, {"step": "entry", "level": "hint"}).json()
    refused = client.post_json(hints, {"step": "map", "level": "do"})
    client.post_json(f"/api/sessions/{session.pk}/close/")

    assert refused.status_code == 400
    assert third["hints"] == [{"lesson": "f1", "step": "entry", "level": "hint"}]
    assert "answer" not in second["progress"]["entry"], "the answer is withheld until the third hint"
    assert third["progress"]["entry"]["answer"]
    detail = client.get(f"/api/sessions/{session.pk}/").json()
    assert detail["hints"] == third["hints"]
    assert detail["progress"]["entry"]["hint"] == 3 and "map" not in detail["progress"]

def test_hints_are_refused_for_a_closed_session_or_one_that_is_not_a_lesson(client):
    closed = foundation("f1")
    client.post_json(f"/api/sessions/{closed.pk}/close/")
    plain = board()

    assert client.post_json(f"/api/sessions/{closed.pk}/lesson/hints/", {"step": "entry", "level": "hint"}).status_code == 409
    assert client.post_json(f"/api/sessions/{plain.pk}/lesson/hints/", {"step": "entry", "level": "hint"}).status_code == 400

def test_reading_the_waf_for_a_poll_waits_on_the_gateway_only_briefly(client):
    session = board(waf={"paranoia": 4, "exclusions": []})
    waited = []

    def runner(adapter, role, segment_id=""):
        def run(argv, stdin=None, timeout=60.0):
            waited.append(timeout)
            return Ran(0, "")
        return run

    with patch("range.docker.Docker.runner", runner):
        assert client.get(f"/api/sessions/{session.pk}/waf/").status_code == 200

    assert waited and max(waited) <= 10, "a WAF box that hangs holds a server thread no longer than this"

def test_a_polled_read_of_the_detections_reads_the_stack_s_shape_once_not_on_every_poll(client):
    from datetime import timedelta

    from django.utils import timezone

    from api.models import Detection

    session = board()
    Detection.objects.create(session=session, detection_id="d1", source="suricata", signature="x",
                             timestamp=timezone.now() + timedelta(seconds=1), src_ip="5.188.10.2")
    read = []

    def segments(adapter):
        read.append(adapter.session)
        return ()

    with patch("range.docker.Docker.segments", segments):
        for _ in range(3):
            assert client.get(f"/api/sessions/{session.pk}/detections/").status_code == 200

    assert read == [session.pk]

def test_listing_closed_sessions_scores_each_once_then_reads_the_stored_result(client):
    for fields in ({"guidance": True, "lesson": "f1"}, {}):
        session = board(**fields)
        red_fires(client, session, output=DUMPED)
        red_submits_the_dump(client, session)
        client.post_json(f"/api/sessions/{session.pk}/close/")
    first = client.get("/api/sessions/?state=closed").json()

    with patch("api.views._evidence", side_effect=AssertionError("scored again")) as scored:
        again = client.get("/api/sessions/?state=closed").json()
        listed = client.get("/api/sessions/").json()

    assert not scored.called, "a list of N closed sessions is N stored reads, not N scorings"
    assert [row["result"] for row in again] == [row["result"] for row in first]
    assert [row["result"] for row in listed if "result" in row] == [row["result"] for row in first]

def test_evidence_that_arrives_after_close_refreshes_the_stored_result(client):
    from datetime import timedelta

    from django.utils import timezone

    from api.models import Detection

    now = timezone.now()
    session = board()
    Case.objects.create(session=session, case_id="c1", name="board-sqli-orderby-sqlmap", malicious=True,
                        correlation="marker", started_at=now - timedelta(seconds=30), ended_at=now - timedelta(seconds=5))
    Objective.objects.create(session=session, key="board-auth-user-admin", name="admin", difficulty=1,
                             achieved_at=now - timedelta(seconds=10))
    client.post_json(f"/api/sessions/{session.pk}/close/")
    before = client.get("/api/sessions/?state=closed").json()[0]["result"]["objectives"]

    Detection.objects.create(session=session, detection_id="late", source="modsecurity", signature="942100",
                             timestamp=now - timedelta(seconds=20), marker="c1")
    after = client.get("/api/sessions/?state=closed").json()[0]["result"]["objectives"]

    assert (before["lost"], before["undetected"]) == (1, 1)
    assert (after["lost"], after["undetected"]) == (1, 0), "an alert ingested after close is in the next list"

def test_the_session_list_can_be_narrowed_to_the_ids_a_browser_remembers(client):
    first, _, third = foundation("f1"), board(), board()
    client.post_json(f"/api/sessions/{first.pk}/close/")

    listed = client.get(f"/api/sessions/?ids={third.pk},{first.pk}").json()

    assert [row["id"] for row in listed] == [third.pk, first.pk]
    assert "result" in listed[1] and listed[1]["lesson_id"] == "f1"
    assert client.get("/api/sessions/?ids=1,x").status_code == 400

def test_an_old_closed_session_whose_lesson_is_gone_still_lists_and_reads(client):
    gone = board(guidance=True, lesson="waf-exclusion", ended_at=timezone.now(),
                 lesson_steps={"waf-exclusion": {"exclude": {"reached": "2026-10-01T00:00:00+00:00", "passed": "2026-10-01T00:05:00+00:00",
                                           "after": 1, "tried": "2026-10-01T00:04:00+00:00"}}},
                 hints=[{"step": "rule", "level": "hint"}])
    old_replays(gone)

    listed = client.get("/api/sessions/").json()
    read = client.get(f"/api/sessions/{gone.pk}/")

    assert [(row["id"], row["kind"], row["lesson_id"]) for row in listed] == [(gone.pk, "lesson", None)]
    assert listed[0]["result"] == {"objectives": {"lost": 0, "undetected": 0, "total": 3}, "scenario": None}
    assert read.status_code == 200, read.content
    assert (read.json()["lesson"], read.json()["lesson_id"]) == (None, None)
    assert read.json()["progress"]["exclude"]["passed"] and "answer" not in read.json()["progress"]["exclude"]

def switch(client, session, lesson_id):
    return client.post_json(f"/api/sessions/{session.pk}/lesson/", {"lesson": lesson_id})

def test_a_foundation_session_moves_to_the_next_lesson_in_place_taking_its_defense_and_seeding_its_logs(client):
    session = foundation("f5", lessons=[{"id": "f5", "started_at": timezone.now().isoformat()}])
    stand = Stand()
    fire, fired = attacker({})
    with patch("range.docker.Docker.runner", stand.runner()), patch("api.views.harness.fire", fire):
        moved = switch(client, session, "f6")

    assert moved.status_code == 200, moved.content
    body = moved.json()
    session.refresh_from_db()
    written = [call for call in stand.to("gateway") if call[3] is not None]
    assert (body["lesson_id"], body["defense"], body["next_lesson"]) == ("f6", "missed", None)
    assert [taken["id"] for taken in body["lessons"]] == ["f5", "f6"]
    assert written and "ruleRemoveById=949110" in written[0][3], "F6's leaking WAF is applied to the open session"
    assert [entry["rule_id"] for entry in session.waf["exclusions"]] == [949110, 959100]
    assert stand.to("sensor") == [], "F5 and F6 run the same IDS rules"
    assert fired == SEEDED and all(case.meta.get("seed") for case in session.cases.all())
    assert session.ended_at is None

def test_a_lesson_switch_is_refused_for_a_closed_scenario_or_unguided_session_and_an_unknown_lesson(client):
    closed, scenario, plain, guided = foundation("f1"), board(guidance=True, lesson="1.1", course_scenario="1.1"), board(), foundation("f1")
    client.post_json(f"/api/sessions/{closed.pk}/close/")

    refused = [switch(client, one, "f2").status_code for one in (closed, scenario, plain)]
    unknown = switch(client, guided, "3.1")

    assert refused == [409, 409, 409]
    assert unknown.status_code == 400 and "3.1" in unknown.json()["detail"]
    assert Session.objects.get(pk=guided.pk).lesson == "f1"

def test_records_kept_before_lessons_chained_are_moved_under_the_session_s_lesson():
    import importlib

    from django.apps import apps

    migration = importlib.import_module("api.migrations.0027_session_lessons")
    old = foundation("f5", lesson_steps={"rule": {"passed": "x"}}, hints=[{"step": "rule", "level": "hint"}])
    scenario = board(guidance=True, lesson="1.1", course_scenario="1.1", lesson_steps={"open": {"passed": "x"}},
                     hints=[{"hint": "find", "level": "hint"}])

    migration.records_kept_per_lesson(apps, None)

    old.refresh_from_db()
    scenario.refresh_from_db()
    assert old.lesson_steps == {"f5": {"rule": {"passed": "x"}}}
    assert old.hints == [{"step": "rule", "level": "hint", "lesson": "f5"}]
    assert old.lessons == [{"id": "f5", "started_at": old.started_at.isoformat()}]
    assert (scenario.lesson_steps, scenario.hints, scenario.lessons) == (
        {"1.1": {"open": {"passed": "x"}}}, [{"hint": "find", "level": "hint"}], [])
