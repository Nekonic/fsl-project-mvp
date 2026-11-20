import pytest

from attack import service
from attack.models import ToolRun
from events import log
from events.kinds import Viewer
from match.models import Round
from tests import rounds
from tests.attack.conftest import codes, url
from testing.fakerange import BR, REFUSED_PAGE, RU, US

pytestmark = pytest.mark.django_db

ATTACK_VIEW = Viewer(sides=frozenset({"attack"}))


@pytest.fixture
def frail(make_round, learner, browser, cloud):
    found = make_round(hp={"budget": 3})
    rounds.seated(found, "attack", learner)
    browser.force_authenticate(learner)
    cloud.box.answer("cr.status=", REFUSED_PAGE)
    return found


def refused(browser, found):
    return browser.post(url(found, "requests/"), {"method": "GET", "path": "/admin/"}, format="json")


def kinds(found):
    return [(event["kind"], event["body"]) for event in log.after(found.pk, 0, ATTACK_VIEW).events
            if event["kind"].startswith("origin")]


def test_the_pool_holds_every_attack_origin_and_the_box_wears_the_default_first(attack_round, cloud):
    [filled] = cloud.edge.matching("nft -f -")

    assert f"add element ip edge pool {{ {RU}" in filled.stdin or RU in filled.stdin
    assert all(address in filled.stdin for address in (RU, US, BR))
    assert "add element ip edge spent" not in filled.stdin
    assert cloud.worn() == [RU]


def test_a_spent_origin_is_dropped_at_the_edge_its_runs_stop_and_the_box_moves_on(frail, browser, cloud):
    running = browser.post(url(frail, "tools/"), {"tool": "nmap", "args": ["-p", "80", "board.com"]},
                           format="json").json()

    answer = refused(browser, frail)

    assert answer.status_code == 200
    assert cloud.edge.matching(f"nft add element ip edge spent {{ {RU} }}")
    assert cloud.edge.matching(f"conntrack -D -s {RU}")
    assert cloud.box.matching(f"kill -TERM")
    assert ToolRun.objects.get(pk=running["run"]).stopped_by == "origin_spent"
    assert cloud.worn() == [RU, BR]
    block = answer.json()["hp"]
    assert (block["origin"]["ip"], block["left"], block["spent"], block["origins_left"]) == (BR, 3, [RU], 2)
    assert answer["X-Origin"] == BR
    assert kinds(frail)[-2:] == [("origin.spent", {"ip": RU}), ("origin.switched", {"ip": BR})]


def test_an_edge_that_refuses_the_spend_still_leaves_the_box_on_the_next_origin(frail, browser, cloud):
    running = browser.post(url(frail, "tools/"), {"tool": "nmap", "args": ["-p", "80", "board.com"]},
                           format="json").json()
    cloud.edge.answer("edge spent", "nft: no such table", exit_code=1)

    answer = refused(browser, frail)

    assert answer.status_code == 503
    assert answer.json()["hp"]["origin"]["ip"] == BR
    assert ToolRun.objects.get(pk=running["run"]).stopped_by == "origin_spent"
    assert cloud.worn() == [RU, BR]
    assert kinds(frail)[-2:] == [("origin.spent", {"ip": RU}), ("origin.switched", {"ip": BR})]


def test_the_next_request_goes_out_from_the_new_origin(frail, browser, cloud):
    from attack.models import Action

    refused(browser, frail)
    answer = refused(browser, frail)

    assert Action.objects.get(pk=answer.json()["action"]).source_ip == BR


def test_a_later_round_on_the_same_lease_starts_with_no_origin_spent_at_the_edge(as_attacker, attacker, cloud):
    as_attacker.post(url(attacker.round, "origins/next/"), format="json")
    first = attacker.round
    first.phase, first.ended = "ended", first.started
    first.save(update_fields=["phase", "ended"])
    later = Round.objects.create(lease=first.lease, problem=first.problem, kind=first.kind, matchup=first.matchup,
                                 phase="running", snapshot=first.snapshot, started=first.started)

    service.fill_pool(later)

    started = cloud.edge.matching("nft -f -")[-1].stdin.splitlines()
    assert started[:2] == ["flush set ip edge pool", "flush set ip edge spent"], (
        "the slot is rebuilt only when the lease is released, so a lease's next round must not inherit "
        "the last round's spent origins")
    assert not any(line.startswith("add element ip edge spent") for line in started)
    assert all(address in "\n".join(started) for address in (RU, US, BR))


def test_the_tick_refill_only_adds_so_a_spend_between_reads_is_never_undone(as_attacker, attacker, cloud):
    as_attacker.post(url(attacker.round, "origins/next/"), format="json")

    service.refill_edge(attacker.round)

    refilled = cloud.edge.matching("nft -f -")[-1].stdin
    assert "flush" not in refilled
    assert f"add element ip edge spent {{ {RU} }}" in refilled


def test_giving_up_an_origin_early_spends_it_and_switches(as_attacker, attacker, cloud):
    answer = as_attacker.post(url(attacker.round, "origins/next/"), format="json")

    assert answer.status_code == 200
    assert answer.json()["origin"]["ip"] == BR
    assert answer.json()["hp"]["spent"] == [RU]
    assert cloud.edge.matching(f"spent {{ {RU} }}")
    assert cloud.worn() == [RU, BR]


def test_once_every_origin_is_spent_every_write_refuses_origins_spent_and_reads_still_answer(frail, browser):
    for _ in range(3):
        refused(browser, frail)

    writes = [
        browser.post(url(frail, "requests/"), {"method": "GET", "path": "/"}, format="json"),
        browser.post(url(frail, "cases/"), {"case": "board-sqli-search"}, format="json"),
        browser.post(url(frail, "tools/"), {"tool": "nmap", "args": []}, format="json"),
        browser.post(url(frail, "loot/"), {"value": []}, format="json"),
        browser.post(url(frail, "origins/next/"), format="json"),
    ]
    read = browser.get(url(frail, "state/"))

    assert [(answer.status_code, codes(answer)) for answer in writes] == [(409, ["origins_spent"])] * 5
    assert all(answer.json()["hp"]["origins_left"] == 0 for answer in writes)
    assert read.status_code == 200 and read.json()["hp"]["origin"] is None
    assert kinds(frail)[-1] == ("origins.spent", {})
    assert sorted(read.json()["hp"]["spent"]) == sorted([RU, US, BR])



def test_the_round_s_end_empties_the_edge_so_the_box_reaches_nothing_between_rounds(as_attacker, attacker, cloud):
    from match import service as match

    match.end_round(attacker.round, "ended_by_operator")

    emptied = cloud.edge.matching("nft -f -")[-1].stdin.splitlines()
    assert emptied == ["flush set ip edge pool", "flush set ip edge spent"], (
        "edge.nft drops every address outside pool, so an empty pool stops a process the learner left on kali "
        "from reaching the target uncharged once the HP rule stops counting")


def test_a_tick_that_finishes_after_the_round_ended_does_not_fill_the_edge_again(as_attacker, attacker, cloud):
    from match import service as match

    match.end_round(attacker.round, "ended_by_operator")
    after = len(cloud.edge.matching("nft -f -"))

    service.refill_edge(attacker.round)

    assert len(cloud.edge.matching("nft -f -")) == after
