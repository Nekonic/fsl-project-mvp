from testing import factories
from tests.shape import refused
from tests.training.round.conftest import bot_round, url
from training.content import problems as content
from training.models import Player, Round
from training.round import lifecycle as service


class LastOne:
    def choice(self, seq):
        return seq[-1]


def test_round_create_refuses_a_card_field(as_learner, allocation, bot_problem, opens_bot_rounds):
    answer = bot_round(as_learner, allocation, bot_problem, opens_bot_rounds, {"step": "1", "card": "A1"})

    refused(answer, 400, "unknown_field", path="players.attack.bot.card")


def test_round_create_draws_the_card_from_the_problems_cards(as_learner, allocation, bot_problem, opens_bot_rounds,
                                                             monkeypatch):
    monkeypatch.setattr(service, "CARD_DRAW", LastOne())

    answer = bot_round(as_learner, allocation, bot_problem, opens_bot_rounds, {"step": "2"})

    assert answer.status_code == 201, answer.content
    seat = Player.objects.get(round_id=answer.json()["round"], side="attack")
    assert (seat.step, seat.card, seat.token_hash) == ("2", "A3", None)
    assert answer.json()["bot_tokens"] == {}


def test_a_defence_bot_seat_has_no_card(as_learner, allocation, opens_bot_rounds):
    attack_problem = content.save_document(factories.round_problem(
        {"side": "attack"}, matchups=["atk_vs_bot"], objectives=["board-auth-user-admin"], bot_steps=["3"],
        cards=["A1"]))

    answer = bot_round(as_learner, allocation, attack_problem, opens_bot_rounds, {"step": "3"}, matchup="atk_vs_bot")

    assert answer.status_code == 201, answer.content
    seat = Player.objects.get(round_id=answer.json()["round"], side="defence")
    assert (seat.step, seat.card) == ("3", "")


def test_round_read_and_debrief_hide_the_card_until_the_end(as_learner, allocation, bot_problem, opens_bot_rounds,
                                                            monkeypatch):
    monkeypatch.setattr(service, "CARD_DRAW", LastOne())
    found = Round.objects.get(pk=bot_round(as_learner, allocation, bot_problem, opens_bot_rounds,
                                           {"step": "1"}).json()["round"])
    service.start_round(found)

    running = as_learner.get(url(found))

    assert running.status_code == 200 and "A3" not in running.content.decode() and "T1190" not in running.content.decode()
    refused(as_learner.get(url(found, "debrief/")), 409, "round_running")
    service.end_round(found, "ended_by_operator")
    shown = as_learner.get(url(found, "debrief/")).json()
    assert shown["card"]["id"] == "A3" and shown["card"]["technique"] == "T1190"
    assert shown["card"]["notice"] == "mitre.copyright"


def test_bot_rounds_are_closed_to_other_accounts(as_learner, allocation, bot_problem, learner, settings):
    settings.BOT_ROUND_USERS = frozenset({"someone-else"})

    refused(bot_round(as_learner, allocation, bot_problem, learner, {"step": "1"}), 403, "bot_rounds_closed")
