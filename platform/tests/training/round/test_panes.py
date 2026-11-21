import json

import pytest

from sandbox.runner import Ran
from testing import fakerange
from tests.shape import refused
from tests.training.round.conftest import pvp, url
from training.content import probes
from training.models import Action, Allocation
from training.round import lifecycle as service


@pytest.fixture
def running(allocation, problem, learner, other):
    return service.start_round(pvp(allocation, problem, other, learner))


CUSTOMER_ADDRESSES = (*fakerange.US_CUSTOMERS, *fakerange.BR_CUSTOMERS)


def site(found, rest="") -> str:
    return f"/site-proxy/{found.pk}/board.com/{rest}"


def test_the_attack_player_s_site_pane_request_is_an_action_like_any_send(browser, cloud, running, other):
    browser.force_authenticate(other)

    answer = browser.get(site(running, "search/?q=hello"))

    assert answer.status_code == 200 and answer.content == b"<p>hello</p>"
    assert answer["X-Origins-Left"] == "3"
    action = Action.objects.get(round=running)
    assert action.kind == "site" and action.meta["path"] == "/search/?q=hello"
    assert any(action.marker in text for text in cloud.in_slot(1).box.texts())


def test_the_defence_player_browses_with_the_allocation_s_marker_from_a_customer_address(browser, cloud, running, learner):
    browser.force_authenticate(learner)

    answer = browser.get(site(running))
    sent = cloud.in_slot(1).customers.matching(running.allocation.browse_marker)

    assert answer.status_code == 200 and "X-Origins-Left" not in answer
    assert not cloud.in_slot(1).box.matching(running.allocation.browse_marker)
    assert not Action.objects.filter(round=running).exists()
    assert sent and any(f"--interface {address}" in sent[-1].text for address in CUSTOMER_ADDRESSES)
    listed = browser.get(url(running, "site/requests/")).json()
    assert [(one["method"], one["url"], one["status"]) for one in listed] == [("GET", "http://board.com/", 200)]
    assert browser.get(url(running, f"site/requests/?after={listed[-1]['id']}")).json() == []


def test_one_player_never_sees_the_other_player_s_site_requests_or_cookies(browser, cloud, running, other, learner):
    box, customers = cloud.in_slot(1).box, cloud.in_slot(1).customers
    box.answer("cr.status=", "HTTP/1.1 200 OK\r\nSet-Cookie: sessionid=attacker\r\n\r\npost\ncr.status=200\n")
    browser.force_authenticate(other)
    browser.get(site(running, "posts/1/"))
    attack_listed = browser.get(url(running, "site/requests/")).json()
    browser.force_authenticate(learner)
    defence_listed = browser.get(url(running, "site/requests/")).json()
    browser.get(site(running))

    assert [one["url"] for one in attack_listed] == ["http://board.com/posts/1/"]
    assert defence_listed == []
    assert "sessionid=attacker" not in customers.matching(running.allocation.browse_marker)[-1].text


def test_the_site_pane_takes_only_the_round_s_hosts_and_only_its_players(browser, running, other, make_user):
    browser.force_authenticate(other)
    refused(browser.get(f"/site-proxy/{running.pk}/elsewhere.com/"), 404, "not_found")
    browser.force_authenticate(make_user("stranger"))
    refused(browser.get(site(running)), 403, "not_a_player")


def test_the_terminal_opens_only_to_the_player_of_its_side_while_the_round_runs(browser, running, other, learner):
    browser.force_authenticate(other)
    assert browser.get(url(running, "terminal-auth/attack")).status_code == 204
    refused(browser.get(url(running, "terminal-auth/defence")), 403, "not_a_player")
    browser.force_authenticate(learner)
    assert browser.get(url(running, "terminal-auth/defence/")).status_code == 204
    refused(browser.get(url(running, "terminal-auth/attack")), 403, "not_a_player")
    service.end_round(running, "ended_by_operator")
    refused(browser.get(url(running, "terminal-auth/defence")), 409, "round_closed")


def test_each_terminal_refusal_names_its_code_in_a_header_nginx_can_read(browser, running, other, learner):
    browser.force_authenticate(other)
    assert browser.get(url(running, "terminal-auth/defence"))["X-Error-Code"] == "not_a_player"
    assert "X-Error-Code" not in browser.get(url(running, "terminal-auth/attack"))
    service.end_round(running, "ended_by_operator")
    assert browser.get(url(running, "terminal-auth/attack"))["X-Error-Code"] == "round_closed"
    assert browser.get("/api/rounds/999999/terminal-auth/attack/")["X-Error-Code"] == "unknown_round"


def test_a_bot_token_opens_its_terminal(browser, allocation, problem, learner):
    made = service.create_round(allocation, problem.pk, "def_vs_bot",
                                {"attack": {"bot": {"name": "claude"}}, "defence": {"username": learner.username}})
    service.start_round(made.round)

    answer = browser.get(url(made.round, "terminal-auth/attack"),
                         HTTP_AUTHORIZATION=f"Bearer {made.bot_tokens['attack']}")

    assert answer.status_code == 204


def test_staff_read_the_range_s_slots(as_staff, cloud, allocation):
    slots = as_staff.get("/api/staff/range/").json()["slots"]

    assert [(one["slot"], one["wargame"], one["allocation"], one["refill"]["state"]) for one in slots] == [
        (1, "board", allocation.pk, "idle"), (2, "corp", None, "idle")]


def test_recording_probes_writes_redacted_recordings_and_a_manifest_then_releases_the_allocation(
        as_staff, cloud, settings, tmp_path, monkeypatch):
    settings.CR_PROBES_OUT = tmp_path / "wargames"
    slot = cloud.in_slot(1)
    slot.box.answer("cr.status=", "HTTP/1.1 200 OK\r\n\r\nadmin hash pbkdf2_sha256$placeholder\ncr.status=200\n")
    node = slot.defence.node_runner("sensor")
    monkeypatch.setattr(type(node), "__call__", recording_node(type(node).__call__))
    monkeypatch.setattr(probes, "threaded", lambda work: work())
    slot.target.answer("/internal/auth-users", json.dumps({"admin": "pbkdf2_sha256$placeholder"}))

    started = as_staff.post("/api/staff/wargames/board/probes/record/")
    allocation_id = started.json()["allocation"]
    progress = as_staff.get(f"/api/staff/probes/{allocation_id}/").json()
    folder = tmp_path / "wargames" / "board" / "probes"
    manifest = json.loads((folder / "manifest.json").read_text())

    assert started.status_code == 202 and progress["state"] == "done", progress
    assert progress["failed"] == [] and len(progress["done"]) == progress["total"]
    assert "board-normal-search" in manifest["cases"] and manifest["image_digest"]
    response = json.loads((folder / "board-sqli-search.response.json").read_text())
    assert "pbkdf2_sha256$placeholder" not in response["body"] and response["status"] == 200
    assert (folder / "board-sqli-search.pcap").read_bytes() == b"pcap"
    assert Allocation.objects.get(pk=allocation_id).closed is not None and slot.resets == 1
    assert "SecRuleEngine DetectionOnly" in slot.defence.gateway.files["/etc/nginx/modsecurity/crs/crs-setup.conf"]
    admitted = " ".join(one.stdin for one in slot.edge.matching("nft -f -"))
    assert slot.worn() and all(f"pool {{ {address} }}" in admitted for address in slot.worn()), (
        "the edge drops every address outside the pool, so the probe allocation admits the origin it wears")


def recording_node(original):
    def answered(self, argv, stdin=None, timeout=60.0):
        text = " ".join(argv)
        if "tcpdump" in text:
            return Ran(0, "4242\n")
        if "base64 -w0" in text:
            return Ran(0, "cGNhcA==")
        return original(self, argv, stdin, timeout)

    return answered


def test_a_recording_longer_than_the_idle_time_keeps_its_allocation(as_staff, cloud, settings, tmp_path, monkeypatch,
                                                                    make_user):
    from datetime import timedelta

    from django.utils import timezone
    from rest_framework.test import APIClient

    settings.CR_PROBES_OUT = tmp_path / "wargames"
    another = APIClient()
    another.force_authenticate(make_user("next-learner"))
    still_open = []

    def idle_past(allocation, declared, case, truth, folder):
        another.post("/api/allocations/", {"wargame": "board"}, format="json")
        still_open.append(Allocation.objects.get(pk=allocation.pk).closed is None)
        Allocation.objects.filter(pk=allocation.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        return {"marker": "m", "malicious": bool(case.get("malicious")), "tool_case": "tool" in case}

    monkeypatch.setattr(probes, "one_case", idle_past)
    monkeypatch.setattr(probes, "threaded", lambda work: work())
    monkeypatch.setattr(probes, "truth_of", lambda allocation, declared: {})

    allocation_id = as_staff.post("/api/staff/wargames/board/probes/record/").json()["allocation"]

    assert still_open and all(still_open)
    assert as_staff.get(f"/api/staff/probes/{allocation_id}/").json()["state"] == "done"


def test_a_second_recording_of_one_wargame_is_refused_while_the_first_holds_an_allocation(as_staff, cloud, monkeypatch):
    monkeypatch.setattr(probes, "threaded", lambda work: None)

    assert as_staff.post("/api/staff/wargames/board/probes/record/").status_code == 202
    refused(as_staff.post("/api/staff/wargames/board/probes/record/"), 409, "probe_running")


def test_each_player_reads_the_learner_map_for_its_own_side(browser, running, other, learner, monkeypatch):
    from sandbox import topology

    drawn = {"zones": [], "nodes": [{"id": "ids", "kind": "sensor"}, {"id": "web", "kind": "server"}],
             "edges": [{"id": "e", "source": "web", "target": "ids"}]}
    monkeypatch.setattr(topology, "graph", lambda learner, wiring: drawn)
    browser.force_authenticate(other)
    attack_map = browser.get(url(running, "topology/")).json()
    browser.force_authenticate(learner)
    defence_map = browser.get(url(running, "topology/")).json()

    assert attack_map == topology.for_side(drawn, "attack")
    assert defence_map == drawn


def test_recording_is_for_staff(as_learner, cloud):
    refused(as_learner.post("/api/staff/wargames/board/probes/record/"), 403, "not_staff")
