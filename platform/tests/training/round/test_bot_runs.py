import pytest
from rest_framework.test import APIClient

from tests.training.round.conftest import bot_round, pvp, url
from training.models import BotRun, Round
from training.round import lifecycle as service

KEY = "launcher-placeholder-key"


@pytest.fixture
def launcher(settings, forget_counts):
    settings.BOT_LAUNCHER_KEY = KEY
    return APIClient(REMOTE_ADDR="203.0.113.8")


def claim(client, key=KEY):
    return client.post("/api/bot-runs/claim/", {"launcher": {"claude_code": "2.1.284"}}, format="json",
                       HTTP_AUTHORIZATION=f"Bearer {key}")


@pytest.fixture
def started(as_learner, allocation, bot_problem, opens_bot_rounds):
    found = Round.objects.get(pk=bot_round(as_learner, allocation, bot_problem, opens_bot_rounds,
                                           {"step": "1"}).json()["round"])
    return service.start_round(found)


def test_starting_a_round_queues_one_run_per_bot_seat_and_a_claim_hands_the_token_once(started, launcher):
    assert list(BotRun.objects.values_list("player__side", "status", "model")) == [
        ("attack", "queued", "claude-haiku-5-5")]

    first = claim(launcher)
    second = claim(launcher)

    assert first.status_code == 200, first.content
    shown = first.json()
    assert (shown["round"], shown["side"], shown["model"], shown["pace"]["per_window"]) == (started.pk, "attack",
                                                                                           "claude-haiku-5-5", 4)
    assert shown["card"]["technique"] and shown["prompt"]["stance"].startswith("Your stance this round")
    assert second.status_code == 204
    launcher.credentials(HTTP_AUTHORIZATION=f"Bearer {shown['token']}")
    assert launcher.get(url(started, "attack/state/")).status_code == 200


def test_a_player_token_cannot_claim(started, launcher):
    token = claim(launcher).json()["token"]
    run = BotRun.objects.get()

    refused = [claim(launcher, token).status_code,
               launcher.post(f"/api/bot-runs/{run.pk}/finish/", {"exit": "success"}, format="json",
                             HTTP_AUTHORIZATION=f"Bearer {token}").status_code,
               launcher.post(f"/api/bot-runs/{run.pk}/notes/", {"notes": []}, format="json",
                             HTTP_AUTHORIZATION=f"Bearer {token}").status_code]

    assert refused == [401, 401, 401]
    assert BotRun.objects.get().status == "running"


def test_the_server_treats_a_bot_seat_as_a_human_seat(started, launcher, allocation, make_user):
    token = claim(launcher).json()["token"]
    as_bot = [launcher.get(url(started, rest), HTTP_AUTHORIZATION=f"Bearer {token}")
              for rest in ("attack/state/", "attack/cases/", "defence/state/")]
    service.end_round(started, "ended_by_operator")
    attacker = make_user("human-attacker")
    human_round = service.start_round(pvp(allocation, started.problem, attacker, make_user("human-defender")))
    launcher.force_authenticate(attacker)
    as_human = [launcher.get(url(human_round, rest)) for rest in ("attack/state/", "attack/cases/", "defence/state/")]

    assert [answer.status_code for answer in as_bot] == [answer.status_code for answer in as_human] == [200, 200, 403]
    assert [sorted(answer.json()) for answer in as_bot[:1]] == [sorted(answer.json()) for answer in as_human[:1]]
    assert len(as_bot[1].json()) == len(as_human[1].json())
