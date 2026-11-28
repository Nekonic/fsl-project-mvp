import json
from datetime import timedelta

import pytest
from django.utils import timezone

from sandbox import service as sandbox
from telemetry.models import Event
from tests.shape import refused
from tests.training.round.conftest import pvp, url
from training.attack import actions as attack
from training.models import Action, CustomerRequest, Origin, Round, RuleSet, RuleTest
from training.round import lifecycle as service
from training.traffic import customers


def read_due(found):
    Round.objects.filter(pk=found.pk).update(read_at=timezone.now() - timedelta(days=1))


@pytest.fixture
def running(allocation, learner, other):
    found = service.start_round(pvp(allocation, other, learner))
    found.snapshot["round"].update(time_limit_s=900, benign_every_s=30)
    found.ends_at = found.started + timedelta(seconds=900)
    found.save(update_fields=["snapshot", "ends_at"])
    read_due(found)
    return found


def test_a_silent_attacker_still_ends_with_true_negatives_from_the_benign_schedule(as_operator, running):
    as_operator.get(url(running, "events/"))
    service.end_round(running, "ended_by_operator")

    totals = as_operator.get(url(running, "score/")).json()["outcomes"]["totals"]

    assert totals["tn"] == len(customers.benign_cases(running)) > 0
    assert totals["tp"] == totals["fn"] == totals["fp"] == 0


def test_every_benign_case_goes_out_once_from_the_infra_box_on_a_customer_address_never_an_attack_origin(cloud,
                                                                                                         running):
    service.catch_up(running)

    sent = CustomerRequest.objects.filter(round=running).exclude(benign_case=None)
    attack_ips = {origin.ip for origin in running.origins.all()}
    slot = cloud.in_slot(1)

    assert sorted(sent.values_list("benign_case", flat=True)) == sorted(customers.benign_cases(running))
    assert sent.count() and not set(sent.values_list("source_ip", flat=True)) & attack_ips
    for one in sent:
        assert len([sent for sent in slot.customers.matching(f"X-Request-ID: {one.marker}")
                    if "/dev/null" in sent.argv]) == 1
        assert f"--interface {one.source_ip}" in slot.customers.matching(one.marker)[0].text
        assert not slot.box.matching(one.marker)
    assert customers.passes(running) == 1


def test_the_benign_pass_waits_its_interval(running):
    service.catch_up(running)
    service.catch_up(running)
    later = timezone.now() + timedelta(seconds=31)
    customers.catch_up(running, later)

    assert customers.passes(running) == 2


def spend_every_origin(found):
    found.origins.update(spent_at=timezone.now(), spent_by="deny")


def test_spent_origins_end_the_round_only_after_one_full_benign_pass(running):
    spend_every_origin(running)
    state = service.state_of(running, timezone.now())

    assert state.benign_passes == 0
    assert service.catch_up(running) == "origins_spent"
    running.refresh_from_db()
    assert running.phase == "ended" and customers.passes(running) == 1


def test_a_read_spends_every_origin_the_waf_error_log_denies_and_the_round_ends(monkeypatch, running):
    from testing.fakes import FakeElastic

    es = FakeElastic()
    for n, origin in enumerate(running.origins.all()):
        stamp = (running.started + timedelta(seconds=n + 1)).isoformat().replace("+00:00", "Z")
        es.add(f"e{n}", {"@timestamp": stamp, "event": {"module": "nginx_error"}, "error": {
            "message": f"2026/11/21 10:00:00 [error] 9#9: *1 access forbidden by rule, client: {origin.ip}, "
                       'server: board.com, request: "GET / HTTP/1.1", host: "board.com"'}})
    monkeypatch.setattr("telemetry.elastic.requests.post", es.post)

    assert service.catch_up(running) == "origins_spent"
    assert not running.origins.filter(spent_at=None).exists()


def test_an_alerts_request_while_elasticsearch_is_down_answers_elastic_unavailable_and_the_other_reads_run(
        monkeypatch, as_operator, running):
    from cr import errors
    from telemetry import alerts as defence

    def down(found):
        raise errors.Unavailable(code="elastic_unavailable")

    monkeypatch.setattr(defence, "ingest_alerts", down)

    refused(as_operator.get(url(running, "defence/alerts/")), 503, "elastic_unavailable")
    assert as_operator.get(url(running, "defence/state/")).status_code == 200
    assert Round.objects.get(pk=running.pk).phase == "running"
    assert customers.passes(running) == 1


def test_another_read_failing_leaves_the_alerts_answer_alone(monkeypatch, as_operator, running):
    from cr import errors

    def down(found):
        raise errors.Unavailable(code="attacker_unavailable")

    monkeypatch.setattr(attack, "read_commands", down)

    assert as_operator.get(url(running, "defence/alerts/")).status_code == 200


def test_the_score_keeps_objectives_outcomes_and_free_actions_apart(as_operator, running, learner):
    attack.send(running, running.players.get(side="attack"), "GET", "/?q=free")
    service.end_round(running, "ended_by_operator")

    score = as_operator.get(url(running, "score/")).json()

    assert set(score) == {"pending", "objectives", "outcomes", "free_actions"}
    assert score["outcomes"]["note"] == "one_case_one_decision"
    assert [one["actions"] for one in score["free_actions"]["by_origin"]] == [1]
    assert score["objectives"]["lost"] == [] and score["objectives"]["kept"]


@pytest.mark.parametrize("side", ["attack", "defence"])
def test_a_player_reads_the_score_only_after_the_end_and_never_picks_the_correlation(browser, allocation,
                                                                                   other, make_user, staff, side):
    defender = make_user("defender")
    found = service.start_round(pvp(allocation, other, defender))
    player = {"attack": other, "defence": defender}[side]
    browser.force_authenticate(player)
    refused(browser.get(url(found, "score/")), 409, "round_running")
    browser.force_authenticate(allocation.opened_by)
    mid_round = browser.get(url(found, "score/"))
    assert mid_round.status_code == 200 and "totals" in mid_round.json()["outcomes"]
    service.end_round(found, "ended_by_operator")

    browser.force_authenticate(player)
    assert browser.get(url(found, "score/")).status_code == 200
    refused(browser.get(url(found, "score/?correlation=window")), 403, "not_staff", path="correlation")
    browser.force_authenticate(staff)
    assert browser.get(url(found, "score/?correlation=window")).status_code == 200


def test_an_operator_who_plays_in_the_round_reads_its_score_only_after_the_end(browser, allocation, other):
    found = service.start_round(pvp(allocation, allocation.opened_by, other))
    browser.force_authenticate(allocation.opened_by)

    refused(browser.get(url(found, "score/")), 409, "round_running")


def test_the_customers_program_starts_with_the_round_and_its_records_land_as_customer_requests(cloud, running):
    customers_box = cloud.in_slot(1).customers
    customers_box.answer("cr.records=", 'cr.records=\n{"marker": "m1", "action": "home", "method": "GET", "path": "/", '
                              '"status": 200, "sent_at": "2026-11-20T00:00:00+00:00"}\n\n=cr.records\n')

    assert running.traffic["running"] is True and customers_box.matching("systemctl start cr-customers.service")
    assert not cloud.in_slot(1).box.matching("cr-customers")
    customers.pull(running)

    assert CustomerRequest.objects.filter(round=running, marker="m1", benign_case=None).exists()


def test_a_round_sets_fresh_board_passwords_and_its_customers_sign_in_with_them(cloud, running):
    slot = cloud.in_slot(1)
    [rotated] = slot.target.matching("set_passwords")
    given = json.loads(rotated.stdin)
    [started] = slot.customers.matching("systemctl start cr-customers.service")
    signed = {user["account"]["username"]: user["account"]["password"]
              for user in json.loads(started.stdin)["users"] if user["account"]}

    assert set(given) == {"jiwoo", "minseo"} and signed and signed.items() <= given.items()
    assert given["jiwoo"] != "jiwoo1234" and given["minseo"] != "minseo1234"
    [read] = slot.target.matching("/internal/auth-users")
    assert slot.target.sent.index(rotated) < slot.target.sent.index(read)
    assert customers.fresh_passwords(running) != customers.fresh_passwords(running)


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
    assert ("round.ended", {"reason": "time_limit"}) in kinds_for(running, "attack")


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

    assert sandbox.keep_refilling(2.0, rounds=2, pause=paused.append) == 2
    assert len(advanced) == 2 and len(paused) == 1


def test_a_failed_rebuild_step_does_not_stop_the_rebuild_job(monkeypatch, cloud, db):
    monkeypatch.setattr(sandbox, "advance_refills", lambda: (_ for _ in ()).throw(RuntimeError("refill bug")))

    assert sandbox.keep_refilling(0.0, rounds=2, pause=lambda seconds: None) == 2


def kinds_for(found, side):
    from telemetry import events as log

    return [(event["kind"], event["body"]) for event in log.after(found.pk, 0, log.Viewer(sides=frozenset({side}))).events]


def test_a_read_judges_each_benign_case_once_the_alert_delay_is_out_and_only_the_defence_sees_it(running):
    service.catch_up(running)
    assert not [kind for kind, _ in kinds_for(running, "defence") if kind == "case.judged"]

    service.judge(running, timezone.now() + timedelta(seconds=31))
    service.judge(running, timezone.now() + timedelta(seconds=62))

    judged = [body for kind, body in kinds_for(running, "defence") if kind == "case.judged"]
    assert sorted(body["case"] for body in judged) == sorted(customers.benign_cases(running))
    assert {(body["verdict"], body["alerts"], body["corroborated"]) for body in judged} == {("tn", 0, None)}
    assert "case.judged" not in [kind for kind, _ in kinds_for(running, "attack")]


def test_the_read_after_the_alert_delay_judges_the_cases_left_before_it_says_the_round_was_judged(
        as_operator, running, settings):
    service.catch_up(running)
    service.end_round(running, "ended_by_operator")
    settings.JUDGE_AFTER_SECONDS = 0

    per_case = as_operator.get(url(running, "score/")).json()["outcomes"]["per_case"]
    shown = [kind for kind, _ in kinds_for(running, "defence")]
    judged = [index for index, kind in enumerate(shown) if kind == "case.judged"]

    assert len(judged) == len(per_case) > 0 and max(judged) < shown.index("round.judged")


def test_a_round_ended_between_reads_reads_the_logs_once_more_before_it_ends(monkeypatch, running):
    read = alerts_read(monkeypatch)
    service.catch_up(running)

    service.end_round(running, "ended_by_operator")

    assert read == [running.pk, running.pk]
    assert Round.objects.get(pk=running.pk).reading_since is None


def test_a_round_ended_while_another_request_holds_the_read_waits_for_it_and_reads_once_more(monkeypatch, running):
    read = alerts_read(monkeypatch)
    Round.objects.filter(pk=running.pk).update(reading_since=timezone.now())
    waited = []

    def holder_finishes():
        waited.append(Round.objects.get(pk=running.pk).phase)
        Round.objects.filter(pk=running.pk).update(reading_since=None)

    monkeypatch.setattr(service, "wait_for_reader", holder_finishes)

    service.end_round(running, "ended_by_operator")

    assert (waited, read) == (["running"], [running.pk])
    assert Round.objects.get(pk=running.pk).phase == "ended"


def test_a_read_that_outlived_its_claim_leaves_the_next_reader_s_claim_alone(monkeypatch, running):
    from telemetry import alerts as alert_feed

    taken_over = timezone.now() + timedelta(minutes=6)
    monkeypatch.setattr(alert_feed, "ingest_alerts",
                        lambda found: Round.objects.filter(pk=found.pk).update(reading_since=taken_over))

    service.catch_up(running)

    assert Round.objects.get(pk=running.pk).reading_since == taken_over


def test_a_read_still_running_when_the_round_ends_stops_and_leaves_the_customers_stopped(monkeypatch, running):
    from telemetry import alerts as alert_feed

    stale = Round.objects.get(pk=running.pk)
    customers.kept(stale, running=True)
    stale.refresh_from_db()

    def ended_meanwhile(found):
        Round.objects.filter(pk=found.pk).update(phase="ended", ended=timezone.now())
        customers.kept(Round.objects.get(pk=found.pk), running=False)

    monkeypatch.setattr(alert_feed, "ingest_alerts", ended_meanwhile)
    fired = []
    monkeypatch.setattr(customers, "fire_pass", lambda found: fired.append(found.pk))

    service.read_logs(stale)

    assert fired == []
    assert Round.objects.get(pk=running.pk).traffic["running"] is False


def test_a_round_past_its_time_on_an_idle_allocation_ends_on_its_time_limit(as_operator, running):
    from training.models import Allocation

    late = running.ends_at - running.started + timedelta(minutes=5)
    Round.objects.filter(pk=running.pk).update(started=running.started - late, ends_at=running.ends_at - late)
    Allocation.objects.filter(pk=running.allocation_id).update(expires_at=timezone.now() - timedelta(seconds=1))

    as_operator.get(url(running))

    ended = Round.objects.get(pk=running.pk)
    assert ended.end_reason == "time_limit" and Allocation.objects.get(pk=running.allocation_id).closed is not None


def suricata_alert(found, marker, seconds):
    stamp = (found.started + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")
    return {"@timestamp": stamp, "timestamp": stamp, "event": {"module": "suricata"}, "event_type": "alert",
            "src_ip": "5.188.10.10", "alert": {"signature_id": 1001, "signature": "SQL injection in search"},
            "http": {"url": "/search/?q=x", "request_headers": [{"name": "X-Request-ID", "value": marker}]}}


def fired_case(browser, found, attacker_user, case):
    browser.force_authenticate(attacker_user)
    answer = browser.post(url(found, "attack/cases/"), {"case": case}, format="json")
    assert answer.status_code == 202, answer.content
    return answer.json()["marker"]


def test_a_fired_case_its_alert_names_ends_the_round_as_a_true_positive_beside_the_benign_true_negatives(
        monkeypatch, browser, running, other, learner):
    from testing.fakes import FakeElastic

    marker = fired_case(browser, running, other, "board-sqli-search")
    es = FakeElastic().add("s1", suricata_alert(running, marker, 1))
    monkeypatch.setattr("telemetry.elastic.requests.post", es.post)
    service.end_round(running, "ended_by_operator")

    browser.force_authenticate(learner)
    totals = browser.get(url(running, "score/")).json()["outcomes"]["totals"]

    assert totals["tp"] == 1
    assert totals["tn"] == len(customers.benign_cases(running)) > 0


def test_an_alert_that_reaches_elasticsearch_after_the_end_counts_once_the_alert_delay_passed(
        monkeypatch, browser, running, other, learner, settings):
    from testing.fakes import FakeElastic

    settings.JUDGE_AFTER_SECONDS = 30
    marker = fired_case(browser, running, other, "board-sqli-search")
    es = FakeElastic()
    monkeypatch.setattr("telemetry.elastic.requests.post", es.post)
    service.end_round(running, "ended_by_operator")
    es.add("s1", suricata_alert(running, marker, 1))
    browser.force_authenticate(learner)

    early = browser.get(url(running, "score/")).json()
    settings.JUDGE_AFTER_SECONDS = 0
    late = browser.get(url(running, "score/")).json()

    assert (early["pending"], early["outcomes"]["totals"]["tp"]) == (True, 0)
    assert (late["pending"], late["outcomes"]["totals"]["tp"]) == (False, 1)
    assert Event.objects.filter(round_id=running.pk, kind="round.judged").count() == 1


def test_the_request_that_ends_a_round_does_not_wait_for_late_alerts(monkeypatch, running, settings):
    slept = []
    monkeypatch.setattr(service.time, "sleep", slept.append)
    settings.JUDGE_AFTER_SECONDS = 30

    ended = service.end_round(running, "ended_by_operator")

    assert slept == [] and ended.phase == "ended" and ended.judged_at is None


def test_the_reads_at_a_round_s_end_fire_no_benign_pass(monkeypatch, running):
    fired = []
    monkeypatch.setattr(customers, "fire_pass", lambda found: fired.append(found.pk))
    monkeypatch.setattr(customers, "due", lambda found, now: True)

    service.end_round(running, "ended_by_operator")

    assert fired == []


def test_an_alert_stamped_after_the_round_ended_does_not_turn_its_case_into_a_true_positive(browser, running, other,
                                                                                           learner):
    from telemetry.models import Detection

    marker = fired_case(browser, running, other, "board-sqli-search")
    service.end_round(running, "ended_by_operator")
    running.refresh_from_db()
    Detection.objects.create(round=running, detection_id="late", engine="ids", rule="1001",
                             signature="SQL injection in search", timestamp=running.ended + timedelta(seconds=1),
                             src_ip="5.188.10.10", marker=marker)

    browser.force_authenticate(learner)
    totals = browser.get(url(running, "score/")).json()["outcomes"]["totals"]

    assert (totals["tp"], totals["fn"]) == (0, 1)


def edge_loads(cloud):
    return [one.stdin or "" for one in cloud.in_slot(1).edge.matching("nft -f -")]


def test_a_read_after_a_spend_never_flushes_the_edge_so_the_spent_origin_stays_dropped(cloud, as_operator, running):
    loaded = edge_loads(cloud)
    attack.next_origin(running, running.players.get(side="attack"))
    read_due(running)

    as_operator.get(url(running, "events/"))

    assert cloud.in_slot(1).edge.matching("add element ip edge spent")
    assert edge_loads(cloud) == loaded


def test_a_read_after_the_round_ended_loads_nothing_into_the_edge(cloud, as_operator, running):
    service.end_round(running, "ended_by_operator")
    emptied = edge_loads(cloud)

    as_operator.get(url(running, "events/"))

    assert edge_loads(cloud) == emptied


def test_a_dump_holding_the_hash_and_an_alert_on_it_lose_nothing_until_the_loot_reaches_the_target_s_truth(
        monkeypatch, cloud, browser, running, other):
    from scoring.models import ObjectiveLoss
    from testing.fakes import BOARD_TRUTH, FakeElastic

    browser.force_authenticate(other)
    fired = browser.post(url(running, "attack/cases/"), {"case": "board-sqli-orderby-sqlmap"}, format="json").json()
    cloud.in_slot(1).box.answer("tail -c +1 ", f"cr.exit=0\ncr.output=\nadmin | {BOARD_TRUTH['admin']}\n")
    dumped = browser.get(url(running, f"attack/tools/{fired['run']}/")).json()
    es = FakeElastic().add("s1", suricata_alert(running, fired["marker"], 1))
    monkeypatch.setattr("telemetry.elastic.requests.post", es.post)
    read_due(running)
    browser.get(url(running, "events/"))

    assert dumped["done"] is True and BOARD_TRUTH["admin"] in dumped["output"]
    assert running.detections.filter(marker=fired["marker"]).exists()
    assert not ObjectiveLoss.objects.filter(round=running).exists()

    loot = {"value": [{"username": "admin", "hash": BOARD_TRUTH["admin"]}]}
    looted = browser.post(url(running, "attack/loot/"), loot, format="json")

    assert looted.json()["lost"] is True
    assert ObjectiveLoss.objects.filter(round=running, key="board-auth-user-admin").exists()


def test_a_response_is_an_origin_the_waf_spent_or_a_tested_version_the_defence_applied_never_a_give_up_or_the_setup(
        running):
    denied, given_up = list(running.origins.all())[:2]
    at = timezone.now()
    Origin.objects.filter(pk=denied.pk).update(spent_at=at, spent_by="deny")
    Origin.objects.filter(pk=given_up.pk).update(spent_at=at, spent_by="player")
    head = RuleSet.objects.filter(round=running, engine="waf").order_by("-version").first()
    passed = RuleTest.objects.create(round=running, engine="waf", sha="x", syntax_ok=True,
                                     result={"passed": True, "actions": [{"marker": "m", "refused": True}]})
    RuleSet.objects.create(round=running, engine="waf", version=head.version + 1, files=head.files, sha="x",
                           source="terminal", applied_at=at, reloaded=at.timestamp() - 5, tested=passed,
                           same_as_tested=True)

    shown = service.responses(running)

    assert {(one.kind, one.source_ip) for one in shown} == {("origin", denied.ip), ("version", None)}
    assert [one.at for one in shown if one.kind == "version"] == [at - timedelta(seconds=5)]


def test_reading_the_allocation_ends_its_round_past_the_time_limit_so_the_lobby_offers_a_new_one(as_operator, running):
    late = running.ends_at - running.started + timedelta(minutes=5)
    Round.objects.filter(pk=running.pk).update(started=running.started - late, ends_at=running.ends_at - late)

    shown = as_operator.get(f"/api/allocations/{running.allocation_id}/").json()

    assert [(line["round"], line["phase"]) for line in shown["rounds"]] == [(running.pk, "ended")]
    assert Round.objects.get(pk=running.pk).end_reason == "time_limit"
