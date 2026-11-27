from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from cr import errors
from sandbox import refill
from sandbox import service as sandbox
from telemetry import events as log
from testing import factories, fakerange
from tests.shape import refused
from tests.training.round.conftest import driven, pvp, url
from training.content import catalog
from training.content import problems as content
from training.defence import rules
from training.models import Allocation, Player, Round
from training.round import allocation as allocations
from training.round import lifecycle as service
from users import players as auth


CRS_SETUP = "/etc/nginx/modsecurity/crs/crs-setup.conf"
RU_US_BR = (fakerange.RU, fakerange.US, fakerange.BR)


def kinds(found):
    return [event["kind"] for event in log.after(found.pk, 0, log.Viewer(staff=True)).events]


def test_opening_an_allocation_takes_a_free_slot_that_serves_the_wargame(as_learner, cloud, learner):
    answer = as_learner.post("/api/allocations/", {"wargame": "board"}, format="json")

    assert answer.status_code == 201, answer.content
    shown = answer.json()
    assert shown["slot"] == 1 and shown["ready"] is True and shown["wargame"] == "board"
    assert Allocation.objects.get(pk=shown["allocation"]).opened_by == learner


def test_a_full_range_answers_range_unavailable_with_a_retry_hint(as_learner, cloud, make_user):
    allocations.open_allocation(make_user("first"), "board")

    second = as_learner.post("/api/allocations/", {"wargame": "board"}, format="json")
    corp = as_learner.post("/api/allocations/", {"wargame": "corp"}, format="json")

    assert refused(second, 503, "range_unavailable")["params"]["retry_after"] > 0
    assert corp.status_code == 201 and corp.json()["slot"] == 2


def test_an_unknown_wargame_is_refused_by_path(as_learner, cloud):
    refused(as_learner.post("/api/allocations/", {"wargame": "nowhere"}, format="json"), 400, "unknown_wargame",
            path="wargame")


def test_a_slot_still_refilling_is_not_offered(as_learner, cloud, settings):
    allocation = allocations.open_allocation(None, "board")
    allocations.close_allocation(allocation)

    refused(as_learner.post("/api/allocations/", {"wargame": "board"}, format="json"), 503, "range_unavailable")
    assert cloud.in_slot(1).resets == 1


def test_a_slot_is_not_offered_while_its_stack_is_being_torn_down(db, cloud, monkeypatch):
    allocation = allocations.open_allocation(None, "board")
    slot = cloud.in_slot(1)
    tearing_down = slot.reset_slot
    ready_meanwhile = []

    def torn_down():
        ready_meanwhile.append(sandbox.slot_ready(1))
        return tearing_down()

    monkeypatch.setattr(slot, "reset_slot", torn_down)
    allocations.close_allocation(allocation)

    assert ready_meanwhile == [False]
    assert refill.standing(sandbox.store(), 1).state == refill.BUILDING


def test_closing_an_allocation_ends_its_rounds_and_the_rebuild_job_refills_the_slot(as_operator, cloud, allocation, problem,
                                                                           learner, other):
    found = pvp(allocation, other, learner)
    service.start_round(found)

    answer = as_operator.post(f"/api/allocations/{allocation.pk}/close/")
    found.refresh_from_db()

    assert answer.status_code == 200 and found.phase == "ended" and found.end_reason == "ended_by_operator"
    assert refill.standing(sandbox.store(), 1).state == refill.BUILDING
    sandbox.advance_refills()
    sandbox.advance_refills()
    assert refill.standing(sandbox.store(), 1).state == refill.IDLE
    assert cloud.in_slot(1).ensured and cloud.in_slot(1).configured == 1


def test_a_heartbeat_pushes_the_expiry_and_a_closed_allocation_takes_none(as_operator, allocation):
    Allocation.objects.filter(pk=allocation.pk).update(expires_at=timezone.now() + timedelta(minutes=1))

    moved = as_operator.post(f"/api/allocations/{allocation.pk}/heartbeat/").json()["expires_at"]
    allocations.close_allocation(allocation)

    assert datetime.fromisoformat(moved.replace("Z", "+00:00")) > timezone.now() + timedelta(minutes=20)
    refused(as_operator.post(f"/api/allocations/{allocation.pk}/heartbeat/"), 409, "allocation_closed")


def test_a_player_heartbeats_the_allocation_but_cannot_close_it_or_end_the_round(browser, allocation, problem, learner, other):
    found = pvp(allocation, other, learner)
    browser.force_authenticate(other)

    assert browser.post(f"/api/allocations/{allocation.pk}/heartbeat/").status_code == 200
    refused(browser.post(f"/api/allocations/{allocation.pk}/close/"), 403, "not_operator")
    refused(browser.post(url(found, "end/")), 403, "not_operator")
    refused(browser.post(url(found, "start/")), 403, "not_operator")


def test_the_round_says_whether_the_viewer_operates_its_allocation(as_operator, browser, allocation, problem, learner, other):
    found = pvp(allocation, other, learner)
    by_operator = as_operator.get(url(found)).json()
    browser.force_authenticate(other)
    by_player = browser.get(url(found)).json()

    assert by_operator["operated"] is True
    assert by_player["operated"] is False


def test_asking_for_a_slot_closes_an_allocation_past_its_limit_and_starts_rebuilding_its_slot(as_learner, cloud,
                                                                                            allocation, problem,
                                                                                            learner, other):
    found = pvp(allocation, other, learner)
    service.start_round(found)
    Allocation.objects.filter(pk=allocation.pk).update(expires_at=timezone.now() - timedelta(seconds=1))

    as_learner.post("/api/allocations/", {"wargame": "board"}, format="json")

    found.refresh_from_db()
    assert Allocation.objects.get(pk=allocation.pk).closed is not None and found.end_reason == "allocation_expired"
    assert refill.standing(sandbox.store(), allocation.slot).state == refill.BUILDING


def test_staff_create_a_bot_round_and_see_the_token_once(as_staff, allocation, problem, learner):
    answer = as_staff.post(f"/api/allocations/{allocation.pk}/rounds/", {
        "problem": problem.pk, "matchup": "def_vs_bot",
        "players": {"attack": {"bot": {"name": "claude"}}, "defence": {"username": learner.username}}}, format="json")

    assert answer.status_code == 201, answer.content
    made = answer.json()
    player = Player.objects.get(round_id=made["round"], side="attack")
    assert player.client == "bot" and player.token_hash == auth.hashed(made["bot_tokens"]["attack"])
    assert sorted(one["side"] for one in made["players"]) == ["attack", "defence"]
    assert "bot_tokens" not in as_staff.get(url(Round.objects.get(pk=made["round"]))).json()


@pytest.mark.parametrize("matchup, players, status, code, path", [
    ("atk_vs_bot", {}, 400, "matchup_not_allowed", "matchup"),
    ("def_vs_bot", {"attack": {"username": "nobody"}, "defence": {"open": True}}, 400, "invalid_choice", "players.attack"),
    ("pvp", {"attack": {"username": "nobody"}, "defence": {"open": True}}, 400, "unknown_account", "players.attack.username"),
])
def test_a_round_the_problem_or_matchup_does_not_allow_is_refused(as_operator, allocation, problem, matchup, players,
                                                                  status, code, path):
    asked = {"matchup": matchup, "players": players, **({} if matchup == "pvp" else {"problem": problem.pk})}
    refused(as_operator.post(f"/api/allocations/{allocation.pk}/rounds/", asked, format="json"),
            status, code, path=path)


def test_an_inactive_account_cannot_be_a_player(as_operator, allocation, problem, learner):
    learner.is_active = False
    learner.save(update_fields=["is_active"])
    refused(as_operator.post(f"/api/allocations/{allocation.pk}/rounds/", {
        "matchup": "pvp",
        "players": {"attack": {"username": learner.username}, "defence": {"open": True}}}, format="json"),
        400, "unknown_account", path="players.attack.username")


def test_players_are_shown_by_username_and_never_by_user_id(as_staff, allocation, problem, learner):
    made = as_staff.post(f"/api/allocations/{allocation.pk}/rounds/", {
        "problem": problem.pk, "matchup": "def_vs_bot",
        "players": {"attack": {"bot": {"name": "claude"}}, "defence": {"username": learner.username}}}, format="json").json()

    shown = {player["side"]: player for player in as_staff.get(f"/api/rounds/{made['round']}/").json()["players"]}
    assert shown["defence"]["username"] == learner.username and shown["attack"]["username"] is None
    assert all("user" not in player and "user_id" not in player for player in shown.values())


def test_one_user_cannot_take_both_players_of_a_round(as_operator, allocation, problem, learner):
    refused(as_operator.post(f"/api/allocations/{allocation.pk}/rounds/", {
        "matchup": "pvp",
        "players": {"attack": {"username": learner.username}, "defence": {"username": learner.username}}}, format="json"),
        409, "already_playing")


def test_a_second_open_round_on_one_allocation_is_refused(allocation, problem, learner, other):
    pvp(allocation, other, learner)

    with pytest.raises(errors.Conflict) as raised:
        pvp(allocation, other, learner)
    assert raised.value.code == "round_open"


def test_joining_an_open_player_takes_it_once(browser, allocation, problem, learner, other, make_user):
    found = service.create_round(allocation, None, "pvp", {"attack": {"open": True},
                                                            "defence": {"username": learner.username}}).round
    browser.force_authenticate(other)

    joined = browser.post(url(found, "players/attack/join/"))
    browser.force_authenticate(make_user("late"))
    late = browser.post(url(found, "players/attack/join/"))
    browser.force_authenticate(learner)
    crossed = browser.post(url(found, "players/attack/join/"))

    assert joined.status_code == 200 and Player.objects.get(round=found, side="attack").user == other
    refused(late, 409, "player_taken")
    refused(crossed, 409, "already_playing")
    assert kinds(found).count("player.joined") == 2


def test_a_round_with_an_open_player_does_not_start(as_operator, allocation, problem, learner):
    found = service.create_round(allocation, None, "pvp", {"attack": {"open": True},
                                                            "defence": {"username": learner.username}}).round

    refused(as_operator.post(url(found, "start/")), 409, "players_open")


def test_starting_freezes_the_snapshot_applies_the_posture_takes_the_baseline_and_fills_the_pool(
        as_operator, cloud, allocation, problem, learner, other):
    found = driven(allocation, problem, learner)

    answer = as_operator.post(url(found, "start/"))
    found.refresh_from_db()

    assert answer.json() == {"phase": "running"}
    assert found.snapshot["problem"]["revision"] == problem.revision and found.baseline
    assert found.ends_at - found.started == timedelta(seconds=900)
    [loaded] = cloud.in_slot(1).edge.matching("nft -f -")
    assert loaded.stdin.splitlines()[2] == f"add element ip edge pool {{ {', '.join(RU_US_BR)} }}"
    assert cloud.in_slot(1).defence.gateway.files[CRS_SETUP] == factories.WAF_FILES[CRS_SETUP]
    assert [(one.version, one.source) for one in rules.versions(found, "waf")] == [(1, "setup")]
    assert "round.started" in kinds(found)
    refused(as_operator.post(url(found, "start/")), 409, "round_started")


def test_a_staff_edit_mid_round_changes_nothing_in_the_running_round(allocation, problem, learner, other):
    from training.content import problems as content

    found = driven(allocation, problem, learner)
    service.start_round(found)
    document = content.export(problem.pk)
    document["problem"]["title"] = "Edited later"
    content.save_document(document, base_revision=problem.revision, problem_id=problem.pk)
    found.refresh_from_db()

    assert found.snapshot["problem"]["title"] == "Placeholder round"


def test_a_failed_start_leaves_the_round_created_to_try_again(monkeypatch, allocation, problem, learner, other):
    from scoring import baseline as referee

    found = pvp(allocation, other, learner)

    def unreachable(*given, **named):
        raise errors.Unavailable(code="ground_truth_unavailable")

    monkeypatch.setattr(referee, "take_baseline", unreachable)
    with pytest.raises(errors.Unavailable):
        service.start_round(found)
    found.refresh_from_db()

    assert found.phase == "created" and found.started is None


def test_an_allocation_where_an_objective_fell_starts_no_new_scored_round(allocation, problem, learner, other):
    from scoring.models import Objective

    found = pvp(allocation, other, learner)
    service.start_round(found)
    Objective.objects.create(round=found, key="board-auth-user-admin", name="admin", achieved_at=timezone.now())
    service.end_round(found, "ended_by_operator")

    with pytest.raises(errors.Conflict) as raised:
        pvp(allocation, other, learner)
    assert raised.value.code == "objective_fallen"

    allocations.close_allocation(allocation)
    sandbox.advance_refills()
    sandbox.advance_refills()
    fresh = allocations.open_allocation(learner, "board")
    assert fresh.pk != allocation.pk and pvp(fresh, other, learner).phase == "created"


@pytest.mark.parametrize("side", ["attack", "defence"])
def test_a_player_forfeits_and_the_round_ends_by_its_side(browser, allocation, problem, learner, other, side):
    found = pvp(allocation, other, learner)
    service.start_round(found)
    browser.force_authenticate({"attack": other, "defence": learner}[side])

    answer = browser.post(url(found, f"{side}/forfeit/"))

    assert answer.status_code == 200 and answer.json()["reason"] == f"forfeit_{side}"
    refused(browser.post(url(found, f"{side}/forfeit/")), 409, "round_closed")
    last = log.after(found.pk, 0, log.Viewer(staff=True)).events[-1]
    assert (last["kind"], last["body"]["reason"]) == ("round.ended", f"forfeit_{side}")


def test_the_operator_ends_a_round_once(as_operator, allocation, problem, learner, other):
    found = pvp(allocation, other, learner)
    service.start_round(found)

    first = as_operator.post(url(found, "end/")).json()
    second = as_operator.post(url(found, "end/")).json()

    assert first == second and first["reason"] == "ended_by_operator"
    assert kinds(found).count("round.ended") == 1


def test_rounds_list_what_the_user_holds_and_what_is_joinable(browser, allocation, problem, learner, other, make_user):
    made = service.create_round(allocation, problem.pk, "def_vs_bot",
                                {"attack": {"bot": {"name": "driven"}}, "defence": {"open": True}}).round
    browser.force_authenticate(make_user("stranger"))

    joinable = browser.get("/api/rounds/?state=joinable").json()
    mine = browser.get("/api/rounds/?mine=1").json()

    [listed] = joinable
    players = {one["side"]: one for one in listed["players"]}
    assert listed["round"] == made.pk and listed["problem_title"] == problem.title
    assert players["defence"]["username"] is None and players["defence"]["bot_name"] == ""
    assert players["attack"]["bot_name"] == "driven"
    assert mine == []


def test_open_rounds_list_only_what_the_user_holds_unless_staff(browser, allocation, problem, learner, other, make_user,
                                                                staff):
    found = pvp(allocation, other, learner)
    browser.force_authenticate(make_user("stranger"))
    assert browser.get("/api/rounds/?state=open").json() == []
    browser.force_authenticate(learner)
    assert [one["round"] for one in browser.get("/api/rounds/?state=open").json()] == [found.pk]
    browser.force_authenticate(staff)
    assert [one["round"] for one in browser.get("/api/rounds/?state=open").json()] == [found.pk]


def test_a_round_ended_while_it_starts_stays_ended(monkeypatch, cloud, allocation, problem, learner, other):
    from training.attack import origins

    found = pvp(allocation, other, learner)
    filled = origins.fill_pool

    def ended_meanwhile(one):
        filled(one)
        service.end_round(service.round_of(one.pk), "ended_by_operator")

    monkeypatch.setattr(origins, "fill_pool", ended_meanwhile)

    started = service.start_round(found)

    assert started.phase == "ended" and started.end_reason == "ended_by_operator"
    assert "round.started" not in kinds(found)
    assert not Round.objects.get(pk=found.pk).traffic.get("running")
    infra = cloud.in_slot(1).customers
    started_customers = infra.matching("systemctl start cr-customers.service")
    stopped_customers = infra.matching("systemctl stop cr-customers.service")
    assert not started_customers or (
        stopped_customers and infra.sent.index(stopped_customers[-1]) > infra.sent.index(started_customers[-1]))


def test_a_bot_token_of_an_ended_round_does_not_keep_the_allocation_alive(browser, allocation, problem, learner):
    made = service.create_round(allocation, problem.pk, "def_vs_bot",
                                {"attack": {"bot": {"name": "claude"}}, "defence": {"username": learner.username}})
    token = f"Bearer {made.bot_tokens['attack']}"
    assert browser.post(f"/api/allocations/{allocation.pk}/heartbeat/", HTTP_AUTHORIZATION=token).status_code == 200
    service.start_round(made.round)
    service.end_round(made.round, "ended_by_operator")

    refused(browser.post(f"/api/allocations/{allocation.pk}/heartbeat/", HTTP_AUTHORIZATION=token), 409, "round_closed")


def test_the_next_allocation_request_closes_an_expired_one_and_prunes_old_closed_ones(as_learner, cloud, make_user,
                                                                                     settings):
    expired = allocations.open_allocation(make_user("away"), "board")
    Allocation.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    old = allocations.open_allocation(make_user("gone"), "corp")
    Allocation.objects.filter(pk=old.pk).update(
        closed=timezone.now() - timedelta(minutes=settings.RETAIN_CLOSED_MINUTES + 1))

    as_learner.post("/api/allocations/", {"wargame": "board"}, format="json")

    assert Allocation.objects.get(pk=expired.pk).closed is not None
    assert not Allocation.objects.filter(pk=old.pk).exists()


def test_a_request_on_an_expired_allocation_closes_it_and_ends_its_round(as_operator, cloud, allocation, problem,
                                                                        learner, other):
    found = service.start_round(pvp(allocation, other, learner))
    Allocation.objects.filter(pk=allocation.pk).update(expires_at=timezone.now() - timedelta(seconds=1))

    refused(as_operator.post(f"/api/allocations/{allocation.pk}/heartbeat/"), 409, "allocation_closed")
    found.refresh_from_db()
    assert found.end_reason == "allocation_expired" and Allocation.objects.get(pk=allocation.pk).closed is not None


def test_a_pvp_round_opens_from_the_wargame_with_its_objectives_and_cases(cloud, allocation, learner, other, settings):
    settings.PVP_TIME_LIMIT_SECONDS = 1800
    found = service.start_round(pvp(allocation, other, learner))
    declared = catalog.read(content.source(), "board")

    assert found.problem is None and found.snapshot["problem"] is None
    assert [one["key"] for one in found.snapshot["objectives"]] == [tier.key for tier in declared.objectives]
    assert found.snapshot["round"]["benign_cases"] == list(declared.benign_cases)
    assert found.snapshot["round"]["time_limit_s"] == 1800


@pytest.mark.parametrize("matchup, players, with_problem, code", [
    ("pvp", {"attack": {"open": True}, "defence": {"open": True}}, True, "problem_not_allowed"),
    ("def_vs_bot", {"attack": {"bot": {"name": "claude"}}, "defence": {"open": True}}, False, "required"),
])
def test_a_pvp_round_takes_no_problem_and_a_bot_round_needs_one(as_staff, allocation, problem, matchup, players,
                                                                with_problem, code):
    asked = {"matchup": matchup, "players": players, **({"problem": problem.pk} if with_problem else {})}

    refused(as_staff.post(f"/api/allocations/{allocation.pk}/rounds/", asked, format="json"), 400, code, path="problem")
