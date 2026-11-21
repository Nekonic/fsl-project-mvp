import pytest

from testing.fakerange import RU
from tests.training.attack.conftest import codes, url

pytestmark = pytest.mark.django_db

HP_KEYS = {"origin", "left", "budget", "origins_left", "spent", "rule"}
RULE = {"budget": 100, "per_request": 1, "refused_x": 3, "burst_per_s": 5, "burst_x": 2,
        "refused_statuses": [400, 403]}


def carries_hp(answer) -> dict:
    assert answer["X-Origin"] == RU
    assert answer["X-Origin-HP"].lstrip("-").isdigit()
    block = answer.json()["hp"]
    assert set(block) == HP_KEYS
    assert block["rule"] == RULE
    assert block["origin"] == {"id": "ru", "label": "Russia", "ip": RU}
    return block


@pytest.mark.parametrize("method, rest, body", [
    ("get", "state/", None),
    ("get", "tools/", None),
    ("post", "requests/", {"method": "GET", "path": "/search/", "query": {"q": "tea"}}),
    ("post", "requests/", {"method": "BREW", "path": "/"}),
    ("post", "requests/", {"method": "GET", "path": "no-slash"}),
    ("post", "cases/", {"case": "no-such-case"}),
    ("post", "cases/", {"case": "board-normal-search-with-apostrophe"}),
    ("post", "tools/", {"tool": "telnet", "args": []}),
    ("get", "tools/999/", None),
    ("delete", "tools/999/", None),
])
def test_every_attack_response_success_or_error_carries_the_hp_block_and_headers(as_attacker, attacker, method,
                                                                                  rest, body):
    answer = getattr(as_attacker, method)(url(attacker.round, rest), body, format="json")

    carries_hp(answer)


def test_the_case_list_carries_the_hp_headers_and_no_expect(as_attacker, attacker):
    answer = as_attacker.get(url(attacker.round, "cases/"))

    assert answer.status_code == 200
    assert answer["X-Origin"] == RU and answer["X-Origin-HP"] == "100"
    assert all(set(case) == {"case", "kind", "malicious", "title"} for case in answer.json())


def test_an_error_names_its_code_beside_the_hp(as_attacker, attacker):
    answer = as_attacker.post(url(attacker.round, "cases/"), {"case": "no-such-case"}, format="json")

    assert answer.status_code == 404
    assert codes(answer) == ["unknown_case"]
    assert carries_hp(answer)["left"] == 100


def test_a_defence_seat_is_refused_and_never_sees_the_attacker_s_hp(browser, attack_round, make_user):
    from tests import rounds

    defender = rounds.seated(attack_round, "defence", make_user("defender"))
    browser.force_authenticate(defender.user)

    answer = browser.get(url(attack_round, "state/"))

    assert answer.status_code == 403
    assert codes(answer) == ["not_seated"]
    assert "hp" not in answer.json() and "X-Origin-HP" not in answer


def test_a_bot_seat_token_reaches_its_attack_routes(browser, attack_round):
    from tests import rounds
    from users import seats as auth

    token = auth.issue_token(rounds.seated(attack_round, "attack", bot_name="claude"))

    answer = browser.get(url(attack_round, "state/"), HTTP_AUTHORIZATION=f"Bearer {token}")

    assert answer.status_code == 200
    assert answer.json()["hp"]["origins_left"] == 3


def test_writes_before_the_start_and_after_the_end_are_refused_with_hp(browser, make_round, learner):
    from tests import rounds

    waiting = make_round(phase="created")
    rounds.seated(waiting, "attack", learner)
    browser.force_authenticate(learner)

    early = browser.post(url(waiting, "requests/"), {"method": "GET", "path": "/"}, format="json")
    waiting.phase = "ended"
    waiting.save(update_fields=["phase"])
    late = browser.post(url(waiting, "requests/"), {"method": "GET", "path": "/"}, format="json")

    assert (early.status_code, codes(early)) == (409, ["round_not_started"])
    assert (late.status_code, codes(late)) == (409, ["round_closed"])
    assert "hp" in early.json() and "hp" in late.json()
