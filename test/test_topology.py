"""The picture of the range has to be the range.

A drawing maintained beside a network is wrong within a session, and a wrong
picture is worse than none because it is believed. This asks the running stack
what shape it is, so the only way for the diagram to be wrong is for the
question to be wrong.

It is the same object as the alert stream, which is the point: every alert is
counted onto the segment it arrived on, and the segments plus what could not
be placed add up to the alerts on the board beside them.
"""

import ipaddress

import pytest
import requests

from conftest import PLATFORM_URL, score_when_ready

CASE = "sqli-login-bypass"


@pytest.fixture(scope="module")
def drawn(stack_is_up):
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={}, timeout=120
    ).json()["id"]
    sent = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
        json={"case": CASE}, timeout=300,
    )
    assert sent.status_code == 201, sent.text
    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", timeout=60)

    def case_detected(totals):
        return any(c["name"] == CASE and c["detected"] for c in totals["per_case"])

    score_when_ready(session_id, until=case_detected)
    shape = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/topology/", timeout=120
    ).json()
    shape["session_id"] = session_id
    shape["detections"] = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/detections/", timeout=120
    ).json()
    return shape


def node(drawn, segment_id):
    return {n["name"] for s in drawn["segments"] if s["id"] == segment_id
            for n in s["nodes"]}


def test_the_picture_has_the_segments_the_stack_actually_has(drawn):
    ids = {s["id"] for s in drawn["segments"]}

    assert {"edge", "estate", "mgmt"} <= ids, sorted(ids)


def test_the_outside_is_outside_and_the_estate_is_not(drawn):
    outside = {s["id"] for s in drawn["segments"] if s["outside"]}

    assert "edge" in outside
    assert "estate" not in outside
    assert "mgmt" not in outside


def test_every_address_on_the_picture_is_on_its_own_subnet(drawn):
    # Read off Docker, never assembled. An address outside the subnet it is
    # drawn on would make the whole diagram a plausible fiction.
    for segment in drawn["segments"]:
        network = ipaddress.ip_network(segment["subnet"])
        for box in segment["nodes"]:
            assert ipaddress.ip_address(box["address"]) in network, (
                f"{box['name']} drawn on {segment['id']} at {box['address']}"
            )


def test_the_waf_has_a_foot_on_each_side(drawn):
    assert "fsl-waf" in node(drawn, "edge")
    assert "fsl-waf" in node(drawn, "estate")


def test_the_target_is_only_ever_on_the_inside(drawn):
    on = {s["id"] for s in drawn["segments"]
          if any(n["name"] == "fsl-juice-shop" for n in s["nodes"])}

    assert on == {"estate"}, (
        f"the target is reachable from {sorted(on)}; an attacker on any "
        f"outside segment could skip the defence entirely"
    )


def test_a_way_in_is_marked_as_one(drawn):
    ways = {n["name"] for s in drawn["segments"] for n in s["nodes"] if n["crosses"]}

    assert "fsl-waf" in ways, f"marked instead: {sorted(ways)}"


def test_the_sensor_is_placed_where_it_watches(drawn):
    # Suricata is on no network of its own - it shares the WAF's namespace -
    # so anything reading only networks draws a range with no IDS in it.
    assert {s["name"] for s in drawn["sensors"]} == {"fsl-suricata"}
    assert drawn["sensors"][0]["watches"] == "fsl-waf"


def test_the_segment_the_attack_arrived_on_carries_it(drawn):
    outside = [s for s in drawn["segments"] if s["outside"]]

    assert sum(s["alerts"] for s in outside), (
        "an attack was fired from outside and no outside segment counted it"
    )


def test_the_diagram_and_the_alert_stream_are_one_object(drawn):
    # The property that makes the picture worth putting beside the alerts: its
    # numbers are those alerts, not a second count that can drift from them.
    placed = sum(s["alerts"] for s in drawn["segments"])

    assert placed + drawn["unplaced"] == len(drawn["detections"]), (
        f"{placed} placed + {drawn['unplaced']} unplaced != "
        f"{len(drawn['detections'])} alerts"
    )


# -- the board's own tables -----------------------------------------------
# An address on its own is not identification. Igloo's write-up of a real
# console names the defect: the device that raised an alert is obvious from
# the alert, but what its source and destination addresses *belong to* takes
# further work - so the console shows the zone beside the address. The rest of
# the dimensions are Cloudflare's: top events by source, by destination, by
# signature, by path.

@pytest.fixture(scope="module")
def top(drawn):
    return requests.get(
        f"{PLATFORM_URL}/api/sessions/{drawn['session_id']}/top/", timeout=120
    ).json()


def test_every_alert_is_counted_against_exactly_one_address(top, drawn):
    addressed = [d for d in drawn["detections"] if d["src_ip"]]

    assert sum(s["alerts"] for s in top["sources"]) == len(addressed)


def test_an_address_is_named_by_the_zone_it_is_actually_on(top, drawn):
    for source in top["sources"]:
        if not source["zone"]:
            continue
        # A zone name covers several segments - every origin is "Internet" -
        # so the address must fall in one of the ranges carrying that name.
        ranges = [ipaddress.ip_network(s["subnet"]) for s in drawn["segments"]
                  if s["name"] == source["zone"]]
        assert any(ipaddress.ip_address(source["src_ip"]) in r for r in ranges), source


def test_the_attack_came_from_outside_and_the_row_says_so(top):
    outside = [s for s in top["sources"] if s["outside"]]

    assert outside, f"nothing outside: {[s['src_ip'] for s in top['sources']]}"

    # Some, not all. A location is learned from whichever alert happened to
    # carry it, and only Suricata's records do - so an address whose alerts in
    # this session were all ModSecurity's has none, which is the honest answer
    # rather than a guess. The bridge gateway is usually that address.
    assert any(s["country"] for s in outside), (
        f"no address on public space resolved to a country: "
        f"{[s['src_ip'] for s in outside]}. The geoip pipeline is not running, "
        f"or the origin ranges stopped resolving."
    )


def test_the_board_says_what_was_attacked_and_how(top):
    # A console showing only where traffic came from is half a console: the
    # pair is source and destination, each with its zone, and the path is
    # where the payload actually is.
    assert top["destinations"], "no destination was recorded for any alert"
    assert any(d["zone"] for d in top["destinations"])
    assert top["paths"], "no request path was recorded for any alert"
    assert all(p["method"] for p in top["paths"])


def test_every_top_table_is_ordered_by_count(top):
    for name in ("sources", "destinations", "signatures", "paths"):
        counts = [row["alerts"] for row in top[name]]
        assert counts == sorted(counts, reverse=True), name
