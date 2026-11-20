from datetime import timedelta

import pytest
from django.utils import timezone

from attack import service as attack
from events import log
from match import customers, follow, service
from match.models import CustomerRequest, Lease, Round
from tests.match.conftest import pvp, url
from tests.shape import refused


@pytest.fixture
def running(lease, problem, learner, other):
    found = pvp(lease, problem, other, learner)
    return service.start_round(found)


def test_a_silent_attacker_still_ends_with_true_negatives_from_the_benign_schedule(as_operator, running):
    service.tick(running)
    service.end_round(running, "ended_by_operator")

    totals = as_operator.get(url(running, "score/")).json()["outcomes"]["totals"]

    assert totals["tn"] >= len(customers.benign_cases(running)) > 0
    assert totals["tp"] == totals["fn"] == totals["fp"] == 0


def test_every_benign_case_goes_out_from_a_customer_address_never_an_attack_origin(running):
    service.tick(running)

    sent = CustomerRequest.objects.filter(round=running).exclude(benign_case=None)
    attack_ips = {origin.ip for origin in running.origin_budgets.all()}

    assert sorted(sent.values_list("benign_case", flat=True)) == sorted(customers.benign_cases(running))
    assert sent.count() and not set(sent.values_list("source_ip", flat=True)) & attack_ips
    assert customers.passes(running) == 1


def test_the_benign_pass_waits_its_interval(running):
    service.tick(running)
    service.tick(running)
    later = timezone.now() + timedelta(seconds=31)
    customers.tick(running, later)

    assert customers.passes(running) == 2


def spend_every_origin(found):
    found.origin_budgets.update(left=0, spent_at=timezone.now())


def test_spent_origins_end_the_round_only_after_one_full_benign_pass(running):
    spend_every_origin(running)
    state = service.state_of(running, timezone.now())

    assert state.benign_passes == 0
    assert service.tick(running) == "origins_spent"
    running.refresh_from_db()
    assert running.phase == "ended" and customers.passes(running) == 1


def test_the_time_limit_ends_the_round(running):
    assert service.tick(running, running.started + timedelta(seconds=901)) == "time_limit"


def test_a_tick_survives_a_side_that_is_unavailable(monkeypatch, running):
    from cr import errors
    from defence import service as defence

    def down(found):
        raise errors.Unavailable(code="elastic_unavailable")

    monkeypatch.setattr(defence, "ingest_alerts", down)

    assert service.tick(running) is None
    assert customers.passes(running) == 1


def test_the_score_keeps_objectives_outcomes_and_free_actions_apart(as_operator, running, learner):
    attack.send(running, running.seats.get(side="attack"), "GET", "/?q=free")
    service.end_round(running, "ended_by_operator")

    score = as_operator.get(url(running, "score/")).json()

    assert set(score) == {"objectives", "outcomes", "free_actions", "posture_drift"}
    assert score["outcomes"]["note"] == "one_case_one_decision"
    assert [one["actions"] for one in score["free_actions"]["by_origin"]] == [1]
    assert score["objectives"]["lost"] == [] and score["objectives"]["kept"]


def test_a_seat_reads_the_score_only_after_the_end_and_never_picks_the_correlation(browser, running, other,
                                                                                   staff):
    browser.force_authenticate(other)
    refused(browser.get(url(running, "score/")), 409, "round_running")
    service.end_round(running, "ended_by_operator")

    assert browser.get(url(running, "score/")).status_code == 200
    refused(browser.get(url(running, "score/?correlation=window")), 403, "not_staff", path="correlation")
    browser.force_authenticate(staff)
    assert browser.get(url(running, "score/?correlation=window")).status_code == 200


def test_neither_seat_reads_the_score_while_the_round_runs(browser, lease, problem, other, make_user):
    defender = make_user("defender")
    found = service.start_round(pvp(lease, problem, other, defender))

    for seat in (other, defender):
        browser.force_authenticate(seat)
        refused(browser.get(url(found, "score/")), 409, "round_running")


def test_the_operator_reads_the_score_mid_round(as_operator, running):
    assert as_operator.get(url(running, "score/")).status_code == 200


def test_the_follower_ticks_running_rounds_closes_expired_leases_and_prunes(running, lease, settings):
    first = follow.once()
    Lease.objects.filter(pk=lease.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    second = follow.once()
    Lease.objects.filter(pk=lease.pk).update(closed=timezone.now() - timedelta(minutes=settings.RETAIN_CLOSED_MINUTES + 1))
    third = follow.once()

    assert first.ticked == (running.pk,)
    assert second.expired == (lease.pk,)
    assert third.pruned == (lease.pk,) and not Round.objects.filter(pk=running.pk).exists()
    assert log.after(running.pk, 0, log.Viewer(staff=True)).events == []


def test_an_unexpected_failure_in_one_step_neither_stops_the_tick_nor_the_follower(monkeypatch, running):
    from defence import service as defence

    def broken(found):
        raise RuntimeError("a bug in one step")

    monkeypatch.setattr(defence, "ingest_alerts", broken)
    ticked = service.tick
    monkeypatch.setattr(service, "advance_refills", lambda: (_ for _ in ()).throw(RuntimeError("refill bug")))
    monkeypatch.setattr(service, "tick", lambda found, now=None: (_ for _ in ()).throw(KeyError("tick bug")))

    followed = follow.once()

    assert followed.refilled == 0 and followed.ticked == (running.pk,) and followed.ended == ()
    assert ticked(running, running.started + timedelta(seconds=901)) == "time_limit"


def test_the_follower_runs_a_fixed_number_of_rounds_without_sleeping_past_the_last(cloud, db):
    paused = []

    assert follow.run(2.0, rounds=2, pause=paused.append) == 2
    assert len(paused) == 1


def test_the_customers_program_starts_with_the_round_and_its_records_land_as_customer_requests(cloud, running):
    box = cloud.in_slot(1).box
    box.answer("cr.records=", 'cr.records=\n{"marker": "m1", "action": "home", "method": "GET", "path": "/", '
                              '"status": 200, "sent_at": "2026-11-20T00:00:00+00:00"}\n\n=cr.records\n')

    assert running.traffic["running"] is True and box.matching("users.py")
    customers.pull(running)

    assert CustomerRequest.objects.filter(round=running, marker="m1", benign_case=None).exists()
