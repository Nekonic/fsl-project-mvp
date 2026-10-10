import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import lesson
from api.models import Case, Objective, Session
from range.ports import Ran
from rules import crs

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
TRUTH = json.loads((FIXTURES / "board-auth-users.json").read_text())
LESSON = [
    "board-sqli-orderby-sqlmap", "board-sqli-orderby-sqlmap-tamper",
    "board-normal-search", "board-normal-search-with-apostrophe",
    "board-normal-post-list", "board-normal-sort",
]
DUMPED = (FIXTURES / "sqlmap-orderby-dump.out").read_text()
HELD = (FIXTURES / "sqlmap-not-injectable.out").read_text()
LOST = (FIXTURES / "sqlmap-host-missing.out").read_text()

class Stand:
    def __init__(self):
        self.calls = []
        self.files = {}

    def runner(self):
        calls, files = self.calls, self.files

        def runner(adapter, role, segment_id=""):
            def run(argv, stdin=None, timeout=60.0):
                calls.append((adapter.session, role, " ".join(argv), stdin))
                if " ".join(argv).endswith(crs.WORKERS):
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

def put(client, session_id, tuning):
    return client.put(
        f"/api/sessions/{session_id}/waf/", json.dumps(tuning), content_type="application/json",
    )

def test_a_session_opens_with_the_full_defense_and_no_guidance_by_default(client):
    opened = client.post_json("/api/sessions/", {}).json()

    assert (opened["guidance"], opened["defense"]) == (False, "full")

@pytest.mark.parametrize("body, refused", [
    ({"defense": "none-such"}, "none-such"),
    ({"defense": ["full"]}, "full"),
    ({"guidance": "yes"}, "guidance"),
    ({"scenario": "corp", "guidance": True}, "no lesson"),
    ({"scenario": "corp", "defense": "minimal"}, "minimal"),
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

def test_a_closed_session_s_waf_is_what_was_recorded(client):
    session = board(waf={"paranoia": 2, "exclusions": []})
    client.post_json(f"/api/sessions/{session.pk}/close/")
    stand = Stand()
    with patch("range.docker.Docker.runner", stand.runner()):
        read = client.get(f"/api/sessions/{session.pk}/waf/").json()

    assert (read["paranoia"], read["file"]) == (2, None)
    assert stand.to("gateway") == []

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

def verify(client, session, outputs):
    fire, fired = attacker(outputs)
    with patch("api.views.harness.fire", fire):
        answer = client.post_json(f"/api/sessions/{session.pk}/verify/")
    assert answer.status_code == 200, answer.content
    return answer.json(), fired

def test_verify_replays_every_lesson_case_and_passes_when_nothing_leaks_and_benign_is_served(client):
    session = board()
    result, fired = verify(client, session, {
        "board-sqli-orderby-sqlmap": HELD, "board-sqli-orderby-sqlmap-tamper": HELD,
    })

    assert fired == LESSON
    assert result["passed"] is True
    assert result["diagnosis"] == [["lesson.diag.blocked_ratio", [2, 2]]]
    assert all(case.meta["verify"] == result["run"] for case in Case.objects.all())

def test_a_variant_that_dumped_the_hashes_fails_verify_on_the_target_s_own_records(client):
    session = board()
    result, _ = verify(client, session, {
        "board-sqli-orderby-sqlmap": HELD, "board-sqli-orderby-sqlmap-tamper": DUMPED,
    })

    assert result["passed"] is False
    assert ["lesson.diag.leaked", ["board-sqli-orderby-sqlmap-tamper", 3, 3]] in result["diagnosis"]
    tamper = Case.objects.get(name="board-sqli-orderby-sqlmap-tamper")
    assert tamper.meta["blocked"] is False and tamper.meta["leaked"] == sorted(TRUTH)

def test_a_dump_that_matches_no_snapshot_account_is_neither_a_leak_nor_a_block(client):
    session = board()
    fake = DUMPED.replace(TRUTH["admin"], "admin1234").replace(TRUTH["jiwoo"], "x").replace(
        TRUTH["minseo"], "y")
    result, _ = verify(client, session, {
        "board-sqli-orderby-sqlmap": fake, "board-sqli-orderby-sqlmap-tamper": HELD,
    })

    assert result["passed"] is False, "sqlmap got rows through, so nothing was blocked"
    assert {"name": "board-sqli-orderby-sqlmap", "malicious": True,
            "outcome": "inconclusive"} in result["cases"]
    assert Objective.objects.count() == 0, "rows that match no account take nothing"

def test_blocking_the_o_brien_search_fails_verify_as_a_benign_case_blocked(client):
    session = board()
    result, _ = verify(client, session, {
        "board-sqli-orderby-sqlmap": HELD, "board-sqli-orderby-sqlmap-tamper": HELD,
        "board-normal-search-with-apostrophe": "http_code=403\n",
    })

    assert result["passed"] is False
    assert ["lesson.diag.benign_blocked", ["board-normal-search-with-apostrophe", 403]] in result["diagnosis"]
    assert {"name": "board-normal-search-with-apostrophe", "malicious": False,
            "outcome": "blocked"} in result["cases"]

def test_a_leak_found_by_verify_takes_the_objectives_it_proves(client):
    session = board()
    verify(client, session, {"board-sqli-orderby-sqlmap": DUMPED})

    assert set(Objective.objects.values_list("key", flat=True)) == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full",
    }

def test_verify_judges_only_its_own_run_not_the_seeded_or_earlier_cases(client):
    session = board()
    verify(client, session, {"board-normal-search-with-apostrophe": "http_code=403\n",
                             "board-sqli-orderby-sqlmap": HELD,
                             "board-sqli-orderby-sqlmap-tamper": HELD})
    result, _ = verify(client, session, {
        "board-sqli-orderby-sqlmap": HELD, "board-sqli-orderby-sqlmap-tamper": HELD,
    })

    assert result["passed"] is True
    assert Case.objects.count() == 2 * len(LESSON)

def test_a_scenario_with_no_lesson_has_nothing_to_verify(client):
    session = Session.objects.create(scenario="corp", baseline=[])

    answer = client.post_json(f"/api/sessions/{session.pk}/verify/")

    assert answer.status_code == 400

def test_a_guided_session_replays_the_lesson_once_at_open_so_its_logs_are_there_to_read(client):
    fire, fired = attacker({})
    with patch("api.views.harness.fire", fire):
        opened = client.post_json("/api/sessions/", {"guidance": True}).json()

    assert fired == LESSON
    assert all(case.meta.get("seed") is True for case in Case.objects.filter(session_id=opened["id"]))
    assert client.get(f"/api/sessions/{opened['id']}/").json()["lesson"]["cases"] == LESSON

def test_an_unguided_session_seeds_nothing_and_shows_no_lesson(client):
    fire, fired = attacker({})
    with patch("api.views.harness.fire", fire):
        opened = client.post_json("/api/sessions/", {}).json()

    assert fired == []
    assert client.get(f"/api/sessions/{opened['id']}/").json()["lesson"] is None

def test_the_verdict_needs_every_attack_held_and_every_benign_case_served():
    held = {"name": "a", "malicious": True, "leaked": [], "accounts": 3, "status": 0,
            "outcome": "held"}
    leaked = dict(held, leaked=["admin"], outcome="leaked")
    unproven = dict(held, outcome="inconclusive")
    served = {"name": "b", "malicious": False, "leaked": [], "accounts": 3, "status": 200}
    blocked = dict(served, status=403)

    assert lesson.verdict([held, served])[0] is True
    assert lesson.verdict([leaked, served])[0] is False
    assert lesson.verdict([unproven, served])[0] is False
    assert lesson.verdict([held, blocked])[0] is False
    assert lesson.verdict([])[0] is False
    assert lesson.verdict([held, leaked, served])[1][0] == ["lesson.diag.blocked_ratio", [1, 2]]

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

@pytest.mark.parametrize("output, exit_code", [
    (LOST, 0),
    (HELD, 1),
    ("", 0),
    (HELD.replace("[*] ending", "[*] still"), 0),
])
def test_a_variant_that_ran_to_no_conclusion_proves_nothing_and_fails_verify(client, output, exit_code):
    session = board()

    def fire(case, launch, target_url):
        if case["name"] == "board-sqli-orderby-sqlmap-tamper":
            return SimpleNamespace(exit_code=exit_code, output=output)
        if case["malicious"]:
            return SimpleNamespace(exit_code=0, output=HELD)
        return SimpleNamespace(exit_code=0, output="http_code=200\n")

    with patch("api.views.harness.fire", fire):
        result = client.post_json(f"/api/sessions/{session.pk}/verify/").json()

    assert result["passed"] is False
    assert ["lesson.diag.inconclusive", ["board-sqli-orderby-sqlmap-tamper"]] in result["diagnosis"]
    assert {"name": "board-sqli-orderby-sqlmap-tamper", "malicious": True,
            "outcome": "inconclusive"} in result["cases"]
    assert result["diagnosis"][0] == ["lesson.diag.blocked_ratio", [1, 2]]

def test_replays_by_the_lesson_are_left_out_of_the_score_but_their_loot_counts(client):
    from api.models import Detection
    from django.utils import timezone

    session = board()
    verify(client, session, {"board-sqli-orderby-sqlmap": DUMPED,
                             "board-sqli-orderby-sqlmap-tamper": HELD})
    marker = Case.objects.get(name="board-normal-search").case_id
    Detection.objects.create(session=session, detection_id="d1", source="modsecurity",
                             signature="920273", timestamp=timezone.now(), marker=marker)
    client.post_json(f"/api/sessions/{session.pk}/close/")

    score = client.get(f"/api/sessions/{session.pk}/score/").json()

    assert (score["tp"], score["fp"], score["fn"], score["tn"]) == (0, 0, 0, 0)
    assert score["unattributed"] == 0, "an alert drawn by a lesson replay is not an orphan"
    assert score["objectives"]["objectives"] == 3, (
        "a real leak matched against the snapshot is still a lost objective"
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

@pytest.mark.parametrize("baseline", [None, {}, []])
def test_verify_refuses_a_session_with_no_snapshot_of_the_target_s_accounts(client, baseline):
    session = Session.objects.create(scenario="board", baseline=baseline)
    fire, fired = attacker({})
    with patch("api.views.harness.fire", fire):
        answer = client.post_json(f"/api/sessions/{session.pk}/verify/")

    assert answer.status_code == 409
    assert "no snapshot" in answer.json()["detail"]
    assert fired == [], "nothing is replayed when no leak could be told from a block"

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

def test_a_finished_lesson_reports_its_last_verdict_and_how_often_it_was_verified(client):
    session = board(guidance=True)
    verify(client, session, {"board-normal-search-with-apostrophe": "http_code=403\n",
                             "board-sqli-orderby-sqlmap": HELD,
                             "board-sqli-orderby-sqlmap-tamper": HELD})
    verify(client, session, {"board-sqli-orderby-sqlmap": HELD,
                             "board-sqli-orderby-sqlmap-tamper": HELD})
    client.post_json(f"/api/sessions/{session.pk}/close/")

    row = client.get("/api/sessions/?state=closed").json()[0]

    assert (row["result"]["lesson"]["passed"], row["result"]["lesson"]["verified"]) == (True, 2)
    assert row["result"]["lesson"]["diagnosis"] == [["lesson.diag.blocked_ratio", [2, 2]]], (
        "the last run's reasons, in the same keys VERIFY answered with"
    )
    assert row["result"]["objectives"] == {"lost": 0, "undetected": 0, "total": 3}

def test_a_finished_session_reports_the_objectives_it_lost_and_how_many_went_unseen(client):
    session = board()
    verify(client, session, {"board-sqli-orderby-sqlmap": DUMPED})
    client.post_json(f"/api/sessions/{session.pk}/close/")

    detail = client.get(f"/api/sessions/{session.pk}/").json()

    assert detail["result"]["objectives"] == {"lost": 3, "undetected": 3, "total": 3}
    assert (detail["result"]["lesson"]["passed"], detail["result"]["lesson"]["verified"]) == (False, 1)

def test_an_unverified_session_has_no_lesson_verdict_to_report(client):
    session = board()
    client.post_json(f"/api/sessions/{session.pk}/close/")

    assert client.get(f"/api/sessions/{session.pk}/").json()["result"]["lesson"] is None

def test_the_session_names_its_waf_box_and_where_the_crs_rules_live(client):
    session = board()

    detail = client.get(f"/api/sessions/{session.pk}/").json()

    assert detail["waf_box"] == f"fsl-{session.pk}-waf"
    assert detail["waf_rules"] == "/etc/modsecurity.d/owasp-crs/rules"

def test_hints_and_done_for_me_are_recorded_on_the_session_and_reported_beside_the_verdict(client):
    session = board(guidance=True)
    hints = f"/api/sessions/{session.pk}/lesson/hints/"

    client.post_json(hints, {"step": "rule", "level": "hint"})
    client.post_json(hints, {"step": "rule", "level": "hint"})
    recorded = client.post_json(hints, {"step": "exclude", "level": "do"}).json()
    verify(client, session, {"board-sqli-orderby-sqlmap": HELD, "board-sqli-orderby-sqlmap-tamper": HELD})
    client.post_json(f"/api/sessions/{session.pk}/close/")

    assert recorded["hints"] == [{"step": "rule", "level": "hint"}, {"step": "exclude", "level": "do"}]
    detail = client.get(f"/api/sessions/{session.pk}/").json()
    assert detail["hints"] == recorded["hints"]
    assert detail["result"]["lesson"]["helped"] == ["hint", "do"]
    assert client.get("/api/sessions/?state=closed").json()[0]["result"]["lesson"]["helped"] == ["hint", "do"]

def test_a_lesson_verified_without_help_reports_none(client):
    session = board(guidance=True)
    verify(client, session, {"board-sqli-orderby-sqlmap": HELD, "board-sqli-orderby-sqlmap-tamper": HELD})

    assert client.get(f"/api/sessions/{session.pk}/").json()["result"]["lesson"]["helped"] == []

@pytest.mark.parametrize("body", [{"step": "nowhere", "level": "hint"}, {"step": "rule", "level": "answer"}, {}])
def test_a_hint_the_lesson_does_not_have_is_refused(client, body):
    session = board(guidance=True)

    assert client.post_json(f"/api/sessions/{session.pk}/lesson/hints/", body).status_code == 400

def test_hints_are_refused_for_a_closed_session_or_one_that_is_not_a_lesson(client):
    closed = board(guidance=True)
    client.post_json(f"/api/sessions/{closed.pk}/close/")
    plain = board()

    assert client.post_json(f"/api/sessions/{closed.pk}/lesson/hints/", {"step": "rule", "level": "hint"}).status_code == 409
    assert client.post_json(f"/api/sessions/{plain.pk}/lesson/hints/", {"step": "rule", "level": "hint"}).status_code == 400

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
