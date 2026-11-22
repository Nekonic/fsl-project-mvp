import shlex
import time
import uuid
from datetime import datetime

import pytest

import plays
from range import ATTACKER, run

GATEWAY = "gateway"
DENY_FILE = "/etc/nginx/conf.d/acceptance-deny.conf"
SETUP = plays.Setup(wargame="board", title="Acceptance origin spend board")
MOST_SENDS = 60
HELD_FOR_S = 240
EVERY_S = 2
GRACE_S = 10.0
CUSTOMER_WAIT = 2 * plays.BENIGN_EVERY_S + 60.0
LOG_WAIT = 240.0
BURST = 40
SLOW_RPM = 30
FAST_RPM = 600
GEO_HTTP = "geo $acceptance_refused {{ default 0; {ip}/32 1; }}\n"
GEO_SITE = "if ($acceptance_refused) { return 403; }\n"
ZONE_HTTP = "limit_req_zone $binary_remote_addr zone={zone}:1m rate={rpm}r/m;\n"
ZONE_SITE = "limit_req zone={zone};\n"
KEEP_ALIVE = """
import http.client, sys, time
log = open(sys.argv[1], "a", buffering=1)
connection = http.client.HTTPConnection("board.com", 80, timeout=5)
deadline = time.time() + float(sys.argv[2])
while time.time() < deadline:
    try:
        connection.request("GET", "/", headers={"Connection": "keep-alive"})
        answered = connection.getresponse()
        answered.read()
        log.write(f"{time.time():.3f} {answered.status}\\n")
        if answered.status != 200:
            break
    except Exception as failed:
        log.write(f"{time.time():.3f} {type(failed).__name__}\\n")
        break
    time.sleep(float(sys.argv[3]))
log.write("end\\n")
"""


def held_connection(allocation: int, log: str) -> None:
    started = run(ATTACKER, ["sh", "-c", f"nohup python3 -c {shlex.quote(KEEP_ALIVE)} {shlex.quote(log)} "
                                         f"{HELD_FOR_S} {EVERY_S} >/dev/null 2>&1 &"], allocation=allocation)
    assert started.ok, f"could not open the held connection on the attacker box: {started.stderr}"


def connection_log(allocation: int, log: str) -> list[tuple[float, str]]:
    read = run(ATTACKER, ["cat", log], allocation=allocation)
    return [(float(at), said) for at, _, said in (line.partition(" ") for line in read.stdout.splitlines())
            if at.replace(".", "", 1).isdigit()]


def denied_at_the_waf(played: plays.Played, ip: str) -> None:
    plays.rule_test_waf(played, {})
    loaded = f"printf 'deny %s;\\n' {shlex.quote(ip)} > {DENY_FILE} && nginx -t && systemctl reload nginx"
    written = run(GATEWAY, ["sh", "-c", loaded], allocation=played.allocation)
    assert written.ok, f"the defender's deny rule did not load on the WAF: {written.stderr}"


def spend_the_first_origin(played: plays.Played) -> tuple[dict, list[plays.Answer]]:
    first = plays.attack_seen(played)["remaining"]["origin"]
    denied_at_the_waf(played, first["ip"])
    answers = []
    for _ in range(MOST_SENDS):
        answer = plays.send(played, "GET", "/")
        answers.append(answer)
        spent = ((answer.body or {}).get("remaining") or {}).get("spent", [])
        if first["ip"] in spent or "origins_spent" in answer.codes:
            break
        time.sleep(plays.POLL)
    return first, answers


def at(stamp: str) -> float:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def spent_after(events: list[dict]) -> float:
    return min((at(event["at"]) for event in events if event["kind"] == "origin.spent"), default=time.time())


def customers_after(played: plays.Played, attack_ips: set[str], since: float) -> list[dict]:
    deadline = time.monotonic() + CUSTOMER_WAIT
    while True:
        seen = [line for line in plays.traffic(played)["by_origin"]
                if line["ip"] not in attack_ips and line["last_at"] and at(line["last_at"]) > since]
        if seen or time.monotonic() >= deadline:
            return seen
        time.sleep(plays.POLL)


@pytest.fixture(scope="module")
def spent_round():
    with plays.Round("board", SETUP) as played:
        log = f"/tmp/cr-held-{uuid.uuid4().hex[:8]}.log"
        held_connection(played.allocation, log)
        time.sleep(3 * EVERY_S)
        first, answers = spend_the_first_origin(played)
        spent_events = [event for event in plays.events(played, {"origin.spent", "origin.switched"})]
        time.sleep(GRACE_S + 2 * EVERY_S)
        held = connection_log(played.allocation, log)
        state = plays.attack_seen(played)
        attack_ips = {origin["ip"] for origin in state["origins"]}
        customers = customers_after(played, attack_ips, spent_after(spent_events) + GRACE_S)
        yield {"first": first, "answers": answers, "events": spent_events, "held": held, "customers": customers,
               "state": state}


def test_every_attack_answer_names_the_origins_left(spent_round):
    assert spent_round["answers"]
    for answer in spent_round["answers"]:
        assert "x-origins-left" in {name.lower() for name in answer.headers}, answer.headers


def test_the_first_origin_is_spent_and_the_box_moves_to_the_next(spent_round):
    kinds = [event["kind"] for event in spent_round["events"]]
    spent = [event for event in spent_round["events"] if event["kind"] == "origin.spent"]

    assert "origin.spent" in kinds and "origin.switched" in kinds, kinds
    assert spent[0]["body"] == {"ip": spent_round["first"]["ip"], "by": "deny"}, spent[0]
    assert spent_round["state"]["remaining"]["origin"]["ip"] != spent_round["first"]["ip"]
    assert spent_round["first"]["ip"] in spent_round["state"]["remaining"]["spent"]


def test_the_edge_drops_the_spent_origin_including_a_connection_held_open_before_the_spend(spent_round):
    spent_at = spent_after(spent_round["events"])
    held = spent_round["held"]
    answered_before = [when for when, said in held if said == "200" and when < spent_at]
    answered_after = [when for when, said in held if said == "200" and when > spent_at + GRACE_S]

    assert answered_before, f"the held connection never got an answer before the spend: {held}"
    assert answered_after == [], (
        f"the keep-alive connection opened from {spent_round['first']['ip']} before it was spent still got answers "
        f"{GRACE_S:.0f}s after the spend: {held}. The infra edge must drop @spent before the established accept")
    assert held and held[-1][1] != "200", f"the held connection never failed: {held}"


def test_customers_keep_reaching_the_target_after_the_spend(spent_round):
    assert spent_round["customers"], (
        "no customer address reached the WAF after an attack origin was spent; the spend reached the customers")


def burst(played: plays.Played) -> None:
    sent = run(ATTACKER, ["sh", "-c", f"for i in $(seq {BURST}); do curl -s -o /dev/null --max-time 10 "
                                      f"http://board.com/ & done; wait"], timeout=120, allocation=played.allocation)
    assert sent.ok, f"the attacker box could not send its burst: {sent.stderr}"


def with_lines(played: plays.Played, base: dict[str, str], http: str, site: str) -> None:
    applied = plays.tune_waf(played, {plays.HTTP_CONF: base[plays.HTTP_CONF].rstrip("\n") + "\n" + http,
                                      plays.SITE_CONF: base[plays.SITE_CONF].rstrip("\n") + "\n" + site})
    assert applied.ok, applied.text


def events_until(played: plays.Played, kind: str, kinds: set[str]) -> list[dict]:
    deadline = time.monotonic() + LOG_WAIT
    while True:
        found = plays.events(played, kinds)
        if any(event["kind"] == kind for event in found) or time.monotonic() >= deadline:
            return found
        time.sleep(plays.POLL)


@pytest.fixture(scope="module")
def limited_round():
    with plays.Round("board", SETUP) as played:
        first = plays.attack_seen(played)["remaining"]["origin"]["ip"]
        base = plays.waf_files(played)
        with_lines(played, base, GEO_HTTP.format(ip=first), GEO_SITE)
        geo = plays.send(played, "GET", "/")
        with_lines(played, base, ZONE_HTTP.format(zone="acceptance_slow", rpm=SLOW_RPM),
                   ZONE_SITE.format(zone="acceptance_slow"))
        burst(played)
        below = events_until(played, "limit.below_floor", {"limit.below_floor", "origin.spent"})
        with_lines(played, base, ZONE_HTTP.format(zone="acceptance_fast", rpm=FAST_RPM),
                   ZONE_SITE.format(zone="acceptance_fast"))
        burst(played)
        above = events_until(played, "origin.spent", {"origin.spent"})
        yield {"first": first, "geo": geo, "below": below, "above": above}


def test_a_geo_return_403_and_a_limit_below_the_floor_spend_nothing(limited_round):
    warned = [event["body"] for event in limited_round["below"] if event["kind"] == "limit.below_floor"]
    spent = [event["body"] for event in limited_round["below"] if event["kind"] == "origin.spent"]

    assert limited_round["geo"].ok and limited_round["geo"].body["status"] == 403, limited_round["geo"].text
    assert warned and warned[0]["zone"] == "acceptance_slow" and SLOW_RPM < warned[0]["floor_rpm"] < FAST_RPM, (
        f"a limit_req below the benign floor left no warning for the defence: {limited_round['below']}")
    assert spent == [], f"a geo 403 or a limit below the floor spent an origin: {spent}"


def test_a_limit_above_the_floor_spends_the_origin_it_refused(limited_round):
    spent = [event["body"] for event in limited_round["above"]]

    assert {"ip": limited_round["first"], "by": "limit_req"} in spent, (
        f"a limit_req above the floor refused {limited_round['first']} and spent nothing: {spent}")
