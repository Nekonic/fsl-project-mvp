import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import lesson
from api.models import Case, Objective, Session
from range.ports import Ran

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parents[2]
TRUTH = {"admin": "h-admin", "jiwoo": "h-jiwoo", "minseo": "h-minseo"}
LESSON = [
    "board-sqli-orderby-sqlmap", "board-sqli-orderby-sqlmap-tamper",
    "board-normal-search", "board-normal-search-with-apostrophe",
    "board-normal-post-list", "board-normal-sort",
]
DUMPED = "| username | password |\n" + "".join(f"| {u} | {h} |\n" for u, h in TRUTH.items())
HELD = "403 (Forbidden) - 94 times\n"

class Stand:
    def __init__(self):
        self.calls = []

    def runner(self):
        calls = self.calls

        def runner(adapter, role, segment_id=""):
            def run(argv, stdin=None, timeout=60.0):
                calls.append((adapter.session, role, " ".join(argv), stdin))
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
def test_a_scenario_without_a_defense_opens_with_its_stack_untouched(client):
    stand = Stand()
    with patch("range.docker.Docker.runner", stand.runner()):
        answer = client.post_json("/api/sessions/", {"scenario": "corp"})

    assert answer.status_code == 201, answer.content
    assert stand.to("gateway") == stand.to("sensor") == []

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
    assert read["version"] == answer.json()["version"]

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

def test_a_dump_that_does_not_match_the_snapshot_is_not_a_leak(client):
    session = board()
    fake = "| username | password |\n| admin | admin1234 |\n"
    result, _ = verify(client, session, {
        "board-sqli-orderby-sqlmap": fake, "board-sqli-orderby-sqlmap-tamper": HELD,
    })

    assert result["passed"] is True

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
    held = {"name": "a", "malicious": True, "leaked": [], "accounts": 3, "status": 0}
    leaked = dict(held, leaked=["admin"])
    served = {"name": "b", "malicious": False, "leaked": [], "accounts": 3, "status": 200}
    blocked = dict(served, status=403)

    assert lesson.verdict([held, served])[0] is True
    assert lesson.verdict([leaked, served])[0] is False
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
