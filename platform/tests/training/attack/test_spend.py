import pytest

from cr import errors
from telemetry import events as log
from telemetry.events import Viewer
from testing.fakerange import BR, RU, US
from testing.fakes import FakeElastic
from tests import rounds
from tests.training.attack.conftest import (
    after_start,
    codes,
    denied_line,
    error_document,
    spent_from_log,
    url,
)
from training.attack import origins
from training.models import Round, ToolRun

pytestmark = pytest.mark.django_db

ATTACK_VIEW = Viewer(sides=frozenset({"attack"}))


@pytest.fixture
def frail(attack_round, learner, browser):
    rounds.playing(attack_round, "attack", learner)
    browser.force_authenticate(learner)
    return attack_round


def denied(found, *ips):
    es = FakeElastic()
    for n, ip in enumerate(ips or (RU,)):
        es.add(f"e{n}", error_document(after_start(found, n + 1), denied_line(ip)))
    return spent_from_log(es, found)


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

    assert denied(frail) == 1

    answer = browser.get(url(frail, "state/"))
    assert cloud.edge.matching(f"nft add element ip edge spent {{ {RU} }}")
    assert cloud.edge.matching(f"conntrack -D -s {RU}")
    assert cloud.box.matching("kill -TERM")
    assert ToolRun.objects.get(pk=running["run"]).stopped_by == "origin_spent"
    assert cloud.worn() == [RU, BR]
    block = answer.json()["remaining"]
    assert (block["origin"]["ip"], block["left"], block["total"], block["spent"]) == (BR, 2, 3, [RU])
    assert (answer["X-Origin"], answer["X-Origins-Left"]) == (BR, "2")
    assert kinds(frail)[-2:] == [("origin.spent", {"ip": RU, "by": "deny"}), ("origin.switched", {"ip": BR})]


def test_an_edge_that_refuses_the_spend_still_leaves_the_box_on_the_next_origin(frail, browser, cloud):
    running = browser.post(url(frail, "tools/"), {"tool": "nmap", "args": ["-p", "80", "board.com"]},
                           format="json").json()
    cloud.edge.answer("edge spent", "nft: no such table", exit_code=1)

    with pytest.raises(errors.Unavailable):
        denied(frail)

    assert origins.remaining(frail).origin.ip == BR
    assert ToolRun.objects.get(pk=running["run"]).stopped_by == "origin_spent"
    assert cloud.worn() == [RU, BR]
    assert kinds(frail)[-2:] == [("origin.spent", {"ip": RU, "by": "deny"}), ("origin.switched", {"ip": BR})]


def test_the_next_request_goes_out_from_the_new_origin(frail, browser, cloud):
    from training.models import Action

    denied(frail)
    answer = browser.post(url(frail, "requests/"), {"method": "GET", "path": "/"}, format="json")

    assert Action.objects.get(pk=answer.json()["action"]).source_ip == BR


def test_a_later_round_on_the_same_allocation_starts_with_no_origin_spent_at_the_edge(as_attacker, attacker, cloud):
    as_attacker.post(url(attacker.round, "origins/next/"), format="json")
    first = attacker.round
    first.phase, first.ended = "ended", first.started
    first.save(update_fields=["phase", "ended"])
    later = Round.objects.create(allocation=first.allocation, problem=first.problem, kind=first.kind, matchup=first.matchup,
                                 phase="running", snapshot=first.snapshot, started=first.started)

    origins.fill_pool(later)

    started = cloud.edge.matching("nft -f -")[-1].stdin.splitlines()
    assert started[:2] == ["flush set ip edge pool", "flush set ip edge spent"], (
        "the slot is rebuilt only when the allocation is released, so an allocation's next round must not inherit "
        "the last round's spent origins")
    assert not any(line.startswith("add element ip edge spent") for line in started)
    assert all(address in "\n".join(started) for address in (RU, US, BR))


def test_giving_up_an_origin_early_spends_it_and_switches(as_attacker, attacker, cloud):
    answer = as_attacker.post(url(attacker.round, "origins/next/"), format="json")

    assert answer.status_code == 200
    assert answer.json()["origin"]["ip"] == BR
    assert answer.json()["remaining"]["spent"] == [RU]
    assert kinds(attacker.round)[-2] == ("origin.spent", {"ip": RU, "by": "player"})
    assert cloud.edge.matching(f"spent {{ {RU} }}")
    assert cloud.worn() == [RU, BR]


def test_once_every_origin_is_spent_every_write_refuses_origins_spent_and_reads_still_answer(frail, browser):
    assert denied(frail, RU, BR, US) == 3

    writes = [
        browser.post(url(frail, "requests/"), {"method": "GET", "path": "/"}, format="json"),
        browser.post(url(frail, "cases/"), {"case": "board-sqli-search"}, format="json"),
        browser.post(url(frail, "tools/"), {"tool": "nmap", "args": []}, format="json"),
        browser.post(url(frail, "loot/"), {"value": []}, format="json"),
        browser.post(url(frail, "origins/next/"), format="json"),
    ]
    read = browser.get(url(frail, "state/"))

    assert [(answer.status_code, codes(answer)) for answer in writes] == [(409, ["origins_spent"])] * 5
    assert all(answer["X-Origins-Left"] == "0" and "remaining" not in answer.json() for answer in writes)
    assert read.status_code == 200 and read.json()["remaining"]["origin"] is None
    assert kinds(frail)[-1] == ("origins.spent", {})
    assert sorted(read.json()["remaining"]["spent"]) == sorted([RU, US, BR])


def test_the_round_s_end_empties_the_edge_so_the_box_reaches_nothing_between_rounds(as_attacker, attacker, cloud):
    from training.round import lifecycle as match

    match.end_round(attacker.round, "ended_by_operator")

    emptied = cloud.edge.matching("nft -f -")[-1].stdin.splitlines()
    assert emptied == ["flush set ip edge pool", "flush set ip edge spent"], (
        "edge.nft drops every address outside pool, so an empty pool stops a process the learner left on kali "
        "from reaching the target once the round no longer reads the WAF's error log")
