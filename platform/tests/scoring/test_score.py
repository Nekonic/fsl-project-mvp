from datetime import datetime, timedelta, timezone

import pytest

from domain.scoring.objectives import RESPONDED_WEIGHT
from domain.types import RESPONSE_VERSION, ResponseRecord
from scoring import baseline as baselines
from scoring import losses
from scoring import score as service
from tests import rounds
from tests.scoring.targets import TRUTH

pytestmark = pytest.mark.django_db

AT = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
SQLI = "board-sqli-search"
BENIGN = "board-normal-search"


def lost_admin(board_target, actions=()):
    found = rounds.opened(rounds.problem(objectives=["board-auth-user-admin", "board-auth-user-full"]),
                          started=AT - timedelta(minutes=30))
    baselines.take_baseline(found, board_target)
    losses.submit_loot(found, {"admin": TRUTH["admin"]}, actions=actions, at=AT)
    return found


def attack_and_customer():
    return [rounds.case(SQLI, AT - timedelta(seconds=20), malicious=True, expect="sql injection"),
            rounds.case(BENIGN, AT - timedelta(seconds=10), malicious=False)]


def test_the_score_keeps_what_was_taken_apart_from_what_the_defence_got_right(board_target):
    actions = attack_and_customer()
    found = lost_admin(board_target, actions)
    alerts = [rounds.detection("d1", AT - timedelta(seconds=19), marker=SQLI, signature="ET WEB SQL Injection")]
    reloaded = [ResponseRecord(at=AT - timedelta(seconds=10), kind=RESPONSE_VERSION, replayed=frozenset({SQLI}),
                               refused=frozenset({SQLI}))]

    scored = service.score(found, actions, alerts, responses=reloaded).shown()

    assert scored["objectives"] == {
        "lost": [{"key": "board-auth-user-admin", "name": "게시판 관리자 계정 탈취", "difficulty": 4, "detected": True,
                  "responded": True, "response_seconds": 9.0, "attributed_marker": SQLI}],
        "kept": [{"key": "board-auth-user-full", "name": "게시판 전체 계정 탈취", "difficulty": 5}],
        "weighted": 2.0,
    }
    assert scored["outcomes"] == {
        "per_case": [{"case": SQLI, "verdict": "tp", "alerts": 1, "corroborated": True},
                     {"case": BENIGN, "verdict": "tn", "alerts": 0, "corroborated": None}],
        "totals": {"tp": 1, "fp": 0, "fn": 0, "tn": 1},
        "note": "one_case_one_decision",
    }
    assert scored["free_actions"] == {"by_origin": []}
    assert set(scored) == {"objectives", "outcomes", "free_actions"}


def test_an_objective_lost_with_no_response_counts_double_even_when_detected(board_target):
    actions = attack_and_customer()
    found = lost_admin(board_target, actions)
    alerts = [rounds.detection("d1", AT - timedelta(seconds=19), marker=SQLI, signature="ET WEB SQL Injection")]

    unanswered = service.score(found, actions, alerts)

    assert (unanswered.lost[0].detected, unanswered.lost[0].responded) == (True, False)
    assert unanswered.weighted == 4.0


def test_an_objective_lost_unseen_and_unanswered_counts_double(board_target):
    actions = attack_and_customer()
    found = lost_admin(board_target, actions)

    unseen = service.score(found, actions, [])

    assert (unseen.lost[0].detected, unseen.lost[0].responded) == (False, False)
    assert unseen.weighted == 4.0
    assert (unseen.totals.tp, unseen.totals.fn) == (0, 1)


def test_each_lost_objective_carries_its_difficulty_so_the_weighted_score_adds_up_from_it(board_target):
    actions = attack_and_customer()
    found = lost_admin(board_target, actions)
    reloaded = [ResponseRecord(at=AT - timedelta(seconds=10), kind=RESPONSE_VERSION, replayed=frozenset({SQLI}),
                               refused=frozenset({SQLI}))]

    for responses, responded in (((), False), (reloaded, True)):
        scored = service.score(found, actions, [], responses=responses)
        assert [(one.difficulty, one.responded) for one in scored.lost] == [(4, responded)]
        assert scored.weighted == sum(one.difficulty * (RESPONDED_WEIGHT if one.responded else 1.0)
                                      for one in scored.lost)


def test_one_declared_case_is_one_decision_however_many_alerts_it_drew(board_target):
    actions = attack_and_customer()
    found = lost_admin(board_target, actions)
    alerts = [rounds.detection(f"d{n}", AT - timedelta(seconds=19), marker=SQLI, signature="ET WEB SQL Injection")
              for n in range(2000)]

    scored = service.score(found, actions, alerts)

    assert scored.per_case[0].alerts == 2000
    assert scored.totals == service.Totals(tp=1, fp=0, fn=0, tn=1)


def test_free_actions_never_enter_tp_fp_fn_tn_and_are_reported_by_origin(board_target):
    declared = attack_and_customer()
    found = lost_admin(board_target, declared)
    free = [rounds.action(f"free-{n}", AT - timedelta(seconds=40 + n)) for n in range(25)]
    alerts = [rounds.detection(f"f{n}", AT - timedelta(seconds=40 + n), marker=f"free-{n}", signature="scan",
                               blocked=n % 2 == 0) for n in range(25)]

    without = service.score(found, declared, [])
    scored = service.score(found, declared + free, alerts)

    assert scored.totals == without.totals
    assert [case.case for case in scored.per_case] == [SQLI, BENIGN]
    assert [vars(origin) for origin in scored.free_actions] == [
        {"ip": rounds.ATTACKER_IP, "actions": 25, "alerts": 25, "refused": 13}]


def test_a_signature_that_fires_on_customers_too_does_not_corroborate_the_attack(board_target):
    actions = attack_and_customer()
    found = lost_admin(board_target, actions)
    alerts = [rounds.detection("d1", AT - timedelta(seconds=19), marker=SQLI, signature="sql injection anywhere"),
              rounds.detection("d2", AT - timedelta(seconds=9), marker=BENIGN, signature="sql injection anywhere")]

    scored = service.score(found, actions, alerts)
    without_customer_alert = service.score(found, actions, alerts[:1])

    assert [(case.verdict, case.corroborated) for case in scored.per_case] == [("tp", False), ("fp", None)]
    assert (scored.totals.fp, without_customer_alert.totals.fp) == (1, 0)
    assert scored.weighted == without_customer_alert.weighted


def test_a_forced_window_correlation_matches_by_source_and_time(board_target):
    actions = attack_and_customer()
    found = lost_admin(board_target, actions)
    unmarked = [rounds.detection("d1", AT - timedelta(seconds=19.5), marker=None, signature="sql injection")]

    by_marker = service.score(found, actions, unmarked)
    by_window = service.score(found, actions, unmarked, correlation="window")

    assert by_marker.totals.tp == 0
    assert by_window.per_case[0].verdict == "tp"


def test_settling_stores_whether_the_defence_saw_each_loss(board_target):
    actions = attack_and_customer()
    found = lost_admin(board_target, actions)
    alerts = [rounds.detection("d1", AT - timedelta(seconds=19), marker=SQLI, signature="sql injection")]
    before = {one.key: one for one in losses.objectives(found)}

    changed = service.settle(found, actions, alerts)

    after = {one.key: one for one in losses.objectives(found)}
    assert before["board-auth-user-admin"].seen is False
    assert changed == 1
    assert after["board-auth-user-admin"] == losses.ObjectiveState(key="board-auth-user-admin",
                                                                   name="게시판 관리자 계정 탈취", state="lost",
                                                                   seen=True)
    assert after["board-auth-user-full"].state == "kept"
    assert service.settle(found, actions, alerts) == 0


def test_a_free_action_carrying_a_malicious_flag_still_stays_out_of_tp_fp_fn_tn(board_target):
    declared = attack_and_customer()
    found = lost_admin(board_target, declared)
    flagged = [rounds.action("free-flagged", AT - timedelta(seconds=50), malicious=True, kind="tool")]

    scored = service.score(found, declared + flagged, [])

    assert scored.totals == service.score(found, declared, []).totals
    assert [case.case for case in scored.per_case] == [SQLI, BENIGN]
    assert [origin.actions for origin in scored.free_actions] == [1]
