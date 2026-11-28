import pytest

from scoring import baseline as referee
from testing.fakerange import RU
from tests.scoring.targets import board_target
from tests.training.attack.conftest import codes, url

pytestmark = pytest.mark.django_db

REMAINING_KEYS = {"origin", "left", "total", "spent"}


WRONG_LOOT = {"value": [{"username": "admin", "hash": "nope"}]}


@pytest.fixture
def answered(as_attacker, attacker):
    referee.take_baseline(attacker.round, board_target())

    def answer(method, rest, body):
        if "{run}" in rest:
            run = as_attacker.post(url(attacker.round, "tools/"), {"tool": "curl", "args": ["-s", "http://board.com/"]},
                                   format="json").json()["run"]
            rest = rest.format(run=run)
        return getattr(as_attacker, method)(url(attacker.round, rest), body, format="json")

    return answer


def carries_origin_headers(answer) -> None:
    assert answer["X-Origin"] == RU
    assert answer["X-Origins-Left"] == "3"


@pytest.mark.parametrize("method, rest, body", [
    ("get", "state/", None),
    ("get", "tools/", None),
    ("get", "cases/", None),
    ("post", "requests/", {"method": "GET", "path": "/search/", "query": {"q": "tea"}}),
    ("post", "requests/", {"method": "BREW", "path": "/"}),
    ("post", "requests/", {"method": "GET", "path": "no-slash"}),
    ("post", "cases/", {"case": "no-such-case"}),
    ("post", "cases/", {"case": "board-normal-search-with-apostrophe"}),
    ("post", "tools/", {"tool": "telnet", "args": []}),
    ("get", "tools/{run}/", None),
    ("delete", "tools/{run}/", None),
    ("get", "tools/999/", None),
    ("delete", "tools/999/", None),
    ("post", "loot/", WRONG_LOOT),
])
def test_every_attack_response_success_or_error_names_the_origin_worn_and_the_origins_left(answered, method, rest,
                                                                                           body):
    answer = answered(method, rest, body)

    carries_origin_headers(answer)


@pytest.mark.parametrize("method, rest, body", [
    ("get", "state/", None),
    ("get", "tools/", None),
    ("post", "requests/", {"method": "GET", "path": "/search/", "query": {"q": "tea"}}),
    ("get", "tools/{run}/", None),
    ("post", "loot/", WRONG_LOOT),
])
def test_a_successful_answer_carries_the_remaining_origins(answered, method, rest, body):
    answer = answered(method, rest, body)

    block = answer.json()["remaining"]
    assert set(block) == REMAINING_KEYS
    assert block == {"origin": {"id": "ru", "label": "Russia", "ip": RU}, "left": 3, "total": 3, "spent": []}


def test_an_error_carries_only_its_errors(as_attacker, attacker):
    answer = as_attacker.post(url(attacker.round, "cases/"), {"case": "no-such-case"}, format="json")

    assert answer.status_code == 404
    assert codes(answer) == ["unknown_case"]
    assert set(answer.json()) == {"errors"}


def test_a_bot_player_token_reaches_its_attack_routes(browser, attack_round):
    from tests import rounds
    from training.round import player_tokens

    token = player_tokens.issue_token(rounds.playing(attack_round, "attack", bot_name="claude"))

    answer = browser.get(url(attack_round, "state/"), HTTP_AUTHORIZATION=f"Bearer {token}")

    assert answer.status_code == 200
    assert answer.json()["round"] == attack_round.pk


def test_writes_before_the_start_and_after_the_end_are_refused(browser, make_round, learner):
    from tests import rounds

    waiting = make_round(phase="created")
    rounds.playing(waiting, "attack", learner)
    browser.force_authenticate(learner)

    early = browser.post(url(waiting, "requests/"), {"method": "GET", "path": "/"}, format="json")
    waiting.phase = "ended"
    waiting.save(update_fields=["phase"])
    late = browser.post(url(waiting, "requests/"), {"method": "GET", "path": "/"}, format="json")

    assert (early.status_code, codes(early)) == (409, ["round_not_started"])
    assert (late.status_code, codes(late)) == (409, ["round_closed"])
