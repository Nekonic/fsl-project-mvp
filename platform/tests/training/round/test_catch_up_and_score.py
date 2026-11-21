from datetime import timedelta

import pytest
from django.utils import timezone

from sandbox import service as sandbox
from tests.shape import refused
from tests.training.round.conftest import pvp, url
from training.attack import actions as attack
from training.models import Action, CustomerRequest, Round
from training.round import lifecycle as service
from training.traffic import customers


def read_due(found):
    Round.objects.filter(pk=found.pk).update(read_at=timezone.now() - timedelta(days=1))


@pytest.fixture
def running(allocation, problem, learner, other):
    found = service.start_round(pvp(allocation, problem, other, learner))
    read_due(found)
    return found


def test_a_silent_attacker_still_ends_with_true_negatives_from_the_benign_schedule(as_operator, running):
    service.catch_up(running)
    service.end_round(running, "ended_by_operator")

    totals = as_operator.get(url(running, "score/")).json()["outcomes"]["totals"]

    assert totals["tn"] >= len(customers.benign_cases(running)) > 0
    assert totals["tp"] == totals["fn"] == totals["fp"] == 0


def test_every_benign_case_goes_out_from_a_customer_address_never_an_attack_origin(running):
    service.catch_up(running)

    sent = CustomerRequest.objects.filter(round=running).exclude(benign_case=None)
    attack_ips = {origin.ip for origin in running.origin_budgets.all()}

    assert sorted(sent.values_list("benign_case", flat=True)) == sorted(customers.benign_cases(running))
    assert sent.count() and not set(sent.values_list("source_ip", flat=True)) & attack_ips
    assert customers.passes(running) == 1


def test_the_benign_pass_waits_its_interval(running):
    service.catch_up(running)
    service.catch_up(running)
    later = timezone.now() + timedelta(seconds=31)
    customers.catch_up(running, later)

    assert customers.passes(running) == 2


def spend_every_origin(found):
    found.origin_budgets.update(left=0, spent_at=timezone.now())


def test_spent_origins_end_the_round_only_after_one_full_benign_pass(running):
    spend_every_origin(running)
    state = service.state_of(running, timezone.now())

    assert state.benign_passes == 0
    assert service.catch_up(running) == "origins_spent"
    running.refresh_from_db()
    assert running.phase == "ended" and customers.passes(running) == 1


def test_the_time_limit_ends_the_round(running):
    assert service.catch_up(running, running.started + timedelta(seconds=901)) == "time_limit"


def test_a_read_survives_a_side_that_is_unavailable(monkeypatch, running):
    from cr import errors
    from telemetry import alerts as defence

    def down(found):
        raise errors.Unavailable(code="elastic_unavailable")

    monkeypatch.setattr(defence, "ingest_alerts", down)

    assert service.catch_up(running) is None
    assert customers.passes(running) == 1


def test_the_score_keeps_objectives_outcomes_and_free_actions_apart(as_operator, running, learner):
    attack.send(running, running.players.get(side="attack"), "GET", "/?q=free")
    service.end_round(running, "ended_by_operator")

    score = as_operator.get(url(running, "score/")).json()

    assert set(score) == {"objectives", "outcomes", "free_actions", "posture_drift"}
    assert score["outcomes"]["note"] == "one_case_one_decision"
    assert [one["actions"] for one in score["free_actions"]["by_origin"]] == [1]
    assert score["objectives"]["lost"] == [] and score["objectives"]["kept"]


def test_a_player_reads_the_score_only_after_the_end_and_never_picks_the_correlation(browser, running, other,
                                                                                   staff):
    browser.force_authenticate(other)
    refused(browser.get(url(running, "score/")), 409, "round_running")
    service.end_round(running, "ended_by_operator")

    assert browser.get(url(running, "score/")).status_code == 200
    refused(browser.get(url(running, "score/?correlation=window")), 403, "not_staff", path="correlation")
    browser.force_authenticate(staff)
    assert browser.get(url(running, "score/?correlation=window")).status_code == 200


def test_neither_player_reads_the_score_while_the_round_runs(browser, allocation, problem, other, make_user):
    defender = make_user("defender")
    found = service.start_round(pvp(allocation, problem, other, defender))

    for player in (other, defender):
        browser.force_authenticate(player)
        refused(browser.get(url(found, "score/")), 409, "round_running")


def test_the_operator_reads_the_score_mid_round(as_operator, running):
    assert as_operator.get(url(running, "score/")).status_code == 200


def test_the_customers_program_starts_with_the_round_and_its_records_land_as_customer_requests(cloud, running):
    box = cloud.in_slot(1).box
    box.answer("cr.records=", 'cr.records=\n{"marker": "m1", "action": "home", "method": "GET", "path": "/", '
                              '"status": 200, "sent_at": "2026-11-20T00:00:00+00:00"}\n\n=cr.records\n')

    assert running.traffic["running"] is True and box.matching("users.py")
    customers.pull(running)

    assert CustomerRequest.objects.filter(round=running, marker="m1", benign_case=None).exists()


def alerts_read(monkeypatch):
    from telemetry import alerts as alert_feed

    read = []
    monkeypatch.setattr(alert_feed, "ingest_alerts", lambda found: read.append(found.pk))
    return read


def test_a_second_request_inside_the_read_interval_reads_nothing_and_one_after_it_reads_again(monkeypatch, running):
    read = alerts_read(monkeypatch)

    service.catch_up(running)
    service.catch_up(running)
    read_due(running)
    service.catch_up(running)

    assert read == [running.pk, running.pk]


def test_a_request_skips_the_reads_while_another_request_holds_them(monkeypatch, running):
    read = alerts_read(monkeypatch)
    Round.objects.filter(pk=running.pk).update(reading_since=timezone.now())

    service.catch_up(running)
    Round.objects.filter(pk=running.pk).update(reading_since=timezone.now() - timedelta(hours=1))
    service.catch_up(running)

    assert read == [running.pk]
    assert Round.objects.get(pk=running.pk).reading_since is None


def test_an_unexpected_failure_in_one_read_does_not_stop_the_others(monkeypatch, running):
    from telemetry import alerts as alert_feed

    def broken(found):
        raise RuntimeError("a bug in one step")

    monkeypatch.setattr(alert_feed, "ingest_alerts", broken)

    assert service.catch_up(running, running.started + timedelta(seconds=901)) == "time_limit"
    assert customers.passes(running) == 1


def test_the_next_request_past_the_time_limit_ends_the_round_at_its_end_time(as_operator, running):
    late = running.ends_at - running.started + timedelta(minutes=5)
    Round.objects.filter(pk=running.pk).update(started=running.started - late, ends_at=running.ends_at - late)
    ends_at = Round.objects.get(pk=running.pk).ends_at

    shown = as_operator.get(url(running)).json()

    ended = Round.objects.get(pk=running.pk)
    assert ended.phase == "ended" and ended.end_reason == "time_limit" and ended.ended == ends_at
    assert shown["phase"] == "ended"


def test_the_score_counts_only_what_happened_up_to_the_round_s_end(as_operator, running):
    attack.send(running, running.players.get(side="attack"), "GET", "/?q=early")
    service.end_round(running, "ended_by_operator")
    running.refresh_from_db()
    later = running.ended + timedelta(seconds=1)
    Action.objects.create(round=running, player=running.players.get(side="attack"), kind="request",
                          marker="late", correlation="marker", source_ip="10.0.0.1", started=later,
                          ended=later, meta={})

    score = as_operator.get(url(running, "score/")).json()

    assert [one["actions"] for one in score["free_actions"]["by_origin"]] == [1]


def test_the_rebuild_job_runs_a_fixed_number_of_rounds_without_sleeping_past_the_last(monkeypatch, cloud, db):
    advanced, paused = [], []
    monkeypatch.setattr(sandbox, "advance_refills", lambda: advanced.append(1) or [])

    assert sandbox.keep_rebuilding(2.0, rounds=2, pause=paused.append) == 2
    assert len(advanced) == 2 and len(paused) == 1


def test_a_failed_rebuild_step_does_not_stop_the_rebuild_job(monkeypatch, cloud, db):
    monkeypatch.setattr(sandbox, "advance_refills", lambda: (_ for _ in ()).throw(RuntimeError("refill bug")))

    assert sandbox.keep_rebuilding(0.0, rounds=2, pause=lambda seconds: None) == 2
