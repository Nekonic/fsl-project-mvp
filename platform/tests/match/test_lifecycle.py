from datetime import timedelta

import pytest
from django.utils import timezone

from events import log
from match import auth, service
from match.models import Lease, Round, Seat
from range import refill
from tests.match.conftest import pvp, url
from tests.shape import refused


def kinds(found):
    return [event["kind"] for event in log.after(found.pk, 0, log.Viewer(staff=True)).events]


def test_opening_a_lease_takes_a_free_slot_that_serves_the_wargame(as_learner, cloud, learner):
    answer = as_learner.post("/api/leases/", {"wargame": "board"}, format="json")

    assert answer.status_code == 201, answer.content
    shown = answer.json()
    assert shown["slot"] == 1 and shown["ready"] is True and shown["wargame"] == "board"
    assert Lease.objects.get(pk=shown["lease"]).opened_by == learner


def test_a_full_range_answers_range_unavailable_with_a_retry_hint(as_learner, cloud, make_user):
    service.open_lease(make_user("first"), "board")

    second = as_learner.post("/api/leases/", {"wargame": "board"}, format="json")
    corp = as_learner.post("/api/leases/", {"wargame": "corp"}, format="json")

    assert refused(second, 503, "range_unavailable")["params"]["retry_after"] > 0
    assert corp.status_code == 201 and corp.json()["slot"] == 2


def test_an_unknown_wargame_is_refused_by_path(as_learner, cloud):
    refused(as_learner.post("/api/leases/", {"wargame": "nowhere"}, format="json"), 400, "unknown_wargame",
            path="wargame")


def test_a_slot_still_refilling_is_not_offered(as_learner, cloud, settings):
    lease = service.open_lease(None, "board")
    service.close_lease(lease)

    refused(as_learner.post("/api/leases/", {"wargame": "board"}, format="json"), 503, "range_unavailable")
    assert cloud.in_slot(1).resets == 1


def test_closing_a_lease_ends_its_rounds_and_the_follower_refills_the_slot(as_operator, cloud, lease, problem,
                                                                           learner, other):
    found = pvp(lease, problem, other, learner)
    service.start_round(found)

    answer = as_operator.post(f"/api/leases/{lease.pk}/close/")
    found.refresh_from_db()

    assert answer.status_code == 200 and found.phase == "ended" and found.end_reason == "ended_by_operator"
    assert refill.standing(service.store(), 1).state == refill.BUILDING
    service.advance_refills()
    service.advance_refills()
    assert refill.standing(service.store(), 1).state == refill.IDLE
    assert cloud.in_slot(1).ensured and cloud.in_slot(1).configured == 1


def test_a_heartbeat_pushes_the_expiry_and_a_closed_lease_takes_none(as_operator, lease):
    Lease.objects.filter(pk=lease.pk).update(expires_at=timezone.now() + timedelta(minutes=1))

    moved = as_operator.post(f"/api/leases/{lease.pk}/heartbeat/").json()["expires_at"]
    service.close_lease(lease)

    assert moved > (timezone.now() + timedelta(minutes=20)).isoformat()
    refused(as_operator.post(f"/api/leases/{lease.pk}/heartbeat/"), 409, "lease_closed")


def test_a_seat_heartbeats_the_lease_but_cannot_close_it_or_end_the_round(browser, lease, problem, learner, other):
    found = pvp(lease, problem, other, learner)
    browser.force_authenticate(other)

    assert browser.post(f"/api/leases/{lease.pk}/heartbeat/").status_code == 200
    refused(browser.post(f"/api/leases/{lease.pk}/close/"), 403, "not_operator")
    refused(browser.post(url(found, "end/")), 403, "not_operator")
    refused(browser.post(url(found, "start/")), 403, "not_operator")


def test_an_expired_lease_is_closed_with_its_round(cloud, lease, problem, learner, other):
    found = pvp(lease, problem, other, learner)
    service.start_round(found)
    Lease.objects.filter(pk=lease.pk).update(expires_at=timezone.now() - timedelta(seconds=1))

    assert service.expire() == [lease.pk]
    found.refresh_from_db()
    assert found.end_reason == "lease_expired" and Lease.objects.get(pk=lease.pk).closed is not None


def test_the_operator_creates_a_bot_round_and_sees_the_token_once(as_operator, lease, problem, learner):
    answer = as_operator.post(f"/api/leases/{lease.pk}/rounds/", {
        "problem": problem.pk, "matchup": "def_vs_bot",
        "seats": {"attack": {"bot": {"name": "claude"}}, "defence": {"user": learner.pk}}}, format="json")

    assert answer.status_code == 201, answer.content
    made = answer.json()
    seat = Seat.objects.get(round_id=made["round"], side="attack")
    assert seat.client == "bot" and seat.token_hash == auth.hashed(made["bot_tokens"]["attack"])
    assert sorted(one["side"] for one in made["seats"]) == ["attack", "defence"]
    assert "bot_tokens" not in as_operator.get(url(Round.objects.get(pk=made["round"]))).json()


@pytest.mark.parametrize("matchup, seats, status, code, path", [
    ("atk_vs_bot", {}, 400, "matchup_not_allowed", "matchup"),
    ("def_vs_bot", {"attack": {"user": 1}, "defence": {"open": True}}, 400, "invalid_choice", "seats.attack"),
    ("pvp", {"attack": {"user": 999}, "defence": {"open": True}}, 400, "does_not_exist", "seats.attack.user"),
])
def test_a_round_the_problem_or_matchup_does_not_allow_is_refused(as_operator, lease, problem, matchup, seats,
                                                                  status, code, path):
    refused(as_operator.post(f"/api/leases/{lease.pk}/rounds/", {"problem": problem.pk, "matchup": matchup,
                                                                 "seats": seats}, format="json"),
            status, code, path=path)


def test_one_user_cannot_take_both_seats_of_a_round(as_operator, lease, problem, learner):
    refused(as_operator.post(f"/api/leases/{lease.pk}/rounds/", {
        "problem": problem.pk, "matchup": "pvp",
        "seats": {"attack": {"user": learner.pk}, "defence": {"user": learner.pk}}}, format="json"),
        409, "already_seated")


def test_a_second_open_round_on_one_lease_is_refused(lease, problem, learner, other):
    pvp(lease, problem, other, learner)

    with pytest.raises(Exception) as raised:
        pvp(lease, problem, other, learner)
    assert raised.value.code == "round_open"


def test_joining_an_open_seat_takes_it_once(browser, lease, problem, learner, other, make_user):
    found = service.create_round(lease, problem.pk, "pvp", {"attack": {"open": True},
                                                            "defence": {"user": learner.pk}}).round
    browser.force_authenticate(other)

    joined = browser.post(url(found, "seats/attack/join/"))
    browser.force_authenticate(make_user("late"))
    late = browser.post(url(found, "seats/attack/join/"))
    browser.force_authenticate(learner)
    crossed = browser.post(url(found, "seats/attack/join/"))

    assert joined.status_code == 200 and Seat.objects.get(round=found, side="attack").user == other
    refused(late, 409, "seat_taken")
    refused(crossed, 409, "already_seated")
    assert kinds(found).count("seat.joined") == 2


def test_a_round_with_an_open_seat_does_not_start(as_operator, lease, problem, learner):
    found = service.create_round(lease, problem.pk, "pvp", {"attack": {"open": True},
                                                            "defence": {"user": learner.pk}}).round

    refused(as_operator.post(url(found, "start/")), 409, "seats_open")


def test_starting_freezes_the_snapshot_applies_the_posture_takes_the_baseline_and_fills_the_pool(
        as_operator, cloud, lease, problem, learner, other):
    found = pvp(lease, problem, other, learner)

    answer = as_operator.post(url(found, "start/"))
    found.refresh_from_db()

    assert answer.json() == {"phase": "running"}
    assert found.snapshot["problem"]["revision"] == problem.revision and found.baseline
    assert found.ends_at - found.started == timedelta(seconds=900)
    assert found.origin_budgets.count() == 3
    assert cloud.in_slot(1).defence.gateway.file
    assert "round.started" in kinds(found)
    refused(as_operator.post(url(found, "start/")), 409, "round_started")


def test_a_staff_edit_mid_round_changes_nothing_in_the_running_round(lease, problem, learner, other):
    from content import service as content

    found = pvp(lease, problem, other, learner)
    service.start_round(found)
    document = content.export(problem.pk)
    document["problem"]["title"] = "Edited later"
    content.save_document(document, base_revision=problem.revision, problem_id=problem.pk)
    found.refresh_from_db()

    assert found.snapshot["problem"]["title"] == "Placeholder round"


def test_a_failed_start_leaves_the_round_created_to_try_again(monkeypatch, lease, problem, learner, other):
    from cr import errors
    from referee import service as referee

    found = pvp(lease, problem, other, learner)

    def unreachable(*given, **named):
        raise errors.Unavailable(code="ground_truth_unavailable")

    monkeypatch.setattr(referee, "take_baseline", unreachable)
    with pytest.raises(errors.Unavailable):
        service.start_round(found)
    found.refresh_from_db()

    assert found.phase == "created" and found.started is None


def test_a_lease_where_an_objective_fell_starts_no_new_scored_round(lease, problem, learner, other):
    from referee.models import Objective

    found = pvp(lease, problem, other, learner)
    service.start_round(found)
    Objective.objects.create(round=found, key="board-auth-user-admin", name="admin", achieved_at=timezone.now())
    service.end_round(found, "ended_by_operator")

    with pytest.raises(Exception) as raised:
        pvp(lease, problem, other, learner)
    assert raised.value.code == "objective_fallen"


def test_a_seat_forfeits_and_the_round_ends_by_its_side(browser, lease, problem, learner, other):
    found = pvp(lease, problem, other, learner)
    service.start_round(found)
    browser.force_authenticate(learner)

    answer = browser.post(url(found, "defence/forfeit/"))

    assert answer.status_code == 200 and answer.json()["reason"] == "forfeit_defence"
    refused(browser.post(url(found, "defence/forfeit/")), 409, "round_closed")
    assert kinds(found)[-1] == "round.ended"


def test_the_operator_ends_a_round_once(as_operator, lease, problem, learner, other):
    found = pvp(lease, problem, other, learner)
    service.start_round(found)

    first = as_operator.post(url(found, "end/")).json()
    second = as_operator.post(url(found, "end/")).json()

    assert first == second and first["reason"] == "ended_by_operator"
    assert kinds(found).count("round.ended") == 1


def test_rounds_list_what_the_user_holds_and_what_is_joinable(browser, lease, problem, learner, other, make_user):
    service.create_round(lease, problem.pk, "pvp", {"attack": {"open": True}, "defence": {"user": learner.pk}})
    browser.force_authenticate(make_user("stranger"))

    joinable = browser.get("/api/rounds/?state=joinable").json()
    mine = browser.get("/api/rounds/?mine=1").json()

    assert len(joinable) == 1 and joinable[0]["seats"]
    assert mine == []


def test_open_rounds_list_only_what_the_user_holds_unless_staff(browser, lease, problem, learner, other, make_user,
                                                                staff):
    found = pvp(lease, problem, other, learner)
    browser.force_authenticate(make_user("stranger"))
    assert browser.get("/api/rounds/?state=open").json() == []
    browser.force_authenticate(learner)
    assert [one["round"] for one in browser.get("/api/rounds/?state=open").json()] == [found.pk]
    browser.force_authenticate(staff)
    assert [one["round"] for one in browser.get("/api/rounds/?state=open").json()] == [found.pk]


def test_a_round_ended_while_it_starts_stays_ended(monkeypatch, lease, problem, learner, other):
    from attack import service as attack

    found = pvp(lease, problem, other, learner)
    filled = attack.fill_pool

    def ended_meanwhile(one):
        filled(one)
        service.end_round(service.round_of(one.pk), "ended_by_operator")

    monkeypatch.setattr(attack, "fill_pool", ended_meanwhile)

    started = service.start_round(found)

    assert started.phase == "ended" and started.end_reason == "ended_by_operator"
    assert "round.started" not in kinds(found)
    assert not Round.objects.get(pk=found.pk).traffic.get("running")


def test_a_bot_token_of_an_ended_round_does_not_keep_the_lease_alive(browser, lease, problem, learner):
    made = service.create_round(lease, problem.pk, "def_vs_bot",
                                {"attack": {"bot": {"name": "claude"}}, "defence": {"user": learner.pk}})
    token = f"Bearer {made.bot_tokens['attack']}"
    assert browser.post(f"/api/leases/{lease.pk}/heartbeat/", HTTP_AUTHORIZATION=token).status_code == 200
    service.start_round(made.round)
    service.end_round(made.round, "ended_by_operator")

    refused(browser.post(f"/api/leases/{lease.pk}/heartbeat/", HTTP_AUTHORIZATION=token), 409, "round_closed")
