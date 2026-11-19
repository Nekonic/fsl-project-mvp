from __future__ import annotations

import json
import os
import threading
import time
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx2
import yaml

from bots import signin
from bots.client.api.attack import (
    attack_cases, attack_fire_case, attack_loot, attack_next_origin, attack_send, attack_start_tool, attack_state,
    attack_tool_output, attack_tools,
)
from bots.client.api.defence import (
    defence_alerts, defence_ids_apply, defence_ids_check, defence_ids_disable, defence_ids_disabled,
    defence_ids_enable, defence_ids_rules, defence_ids_test, defence_ids_versions, defence_probes, defence_state,
    defence_terminal, defence_traffic, defence_waf, defence_waf_apply, defence_waf_test, defence_waf_versions,
)
from bots.client.api.match import (
    lease_close, lease_heartbeat, lease_open, round_create, round_end, round_events, round_list, round_read, round_score,
    round_start, round_topology,
)
from bots.client.api.staff import (
    staff_problem, staff_problem_create, staff_problem_update, staff_problems, staff_range, staff_users,
)
from bots.client.models import RoundListState, RoundScoreCorrelation
from opening import refused_for_room

REPO_ROOT = Path(__file__).resolve().parent.parent
PLATFORM_URL = os.environ.get("CR_PLATFORM_URL", "http://localhost:8000").rstrip("/")
DECLARED_RULES = REPO_ROOT / "deploy/suricata/rules/local.rules"
CASES = REPO_ROOT / "redteam/cases"
WARGAMES = REPO_ROOT / "wargames"
TITLE = "Acceptance {wargame}"
BOT = "acceptance"
DETECT_WITHOUT_BLOCKING_SEARCH = {
    "paranoia": 1,
    "exclusions": [{"rule_id": 949110, "target": "", "path": "/search/"}],
}
HP = {"budget": 1000000, "per_request": 1, "refused_x": 1, "burst_per_s": 1000, "burst_x": 1}
BENIGN_EVERY_S = 30
ROOM_WAIT = 1800
POLL = 2
SCORE_WAIT = 150.0
TOOL_WAIT = 900.0
ALERT_PAGES = 200
HEARTBEAT_EVERY = 60.0


@dataclass(frozen=True)
class Answer:
    status: int
    body: Any
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def codes(self) -> list[str]:
        if isinstance(self.body, dict):
            return [item.get("code", "") for item in self.body.get("errors") or []]
        return []

    @property
    def text(self) -> str:
        return json.dumps(self.body)[:2000]


def body_model(operation):
    hinted = typing.get_type_hints(operation.sync_detailed)["body"]
    return next(kind for kind in (typing.get_args(hinted) or (hinted,)) if hasattr(kind, "from_dict"))


def ask(operation, client, body: dict | None = None, **named) -> Answer:
    if body is not None:
        named["body"] = body_model(operation).from_dict(body)
    answered = operation.sync_detailed(client=client, **named)
    parsed = json.loads(answered.content) if answered.content else None
    return Answer(int(answered.status_code), parsed, dict(answered.headers))


def done(operation, client, body: dict | None = None, **named) -> Any:
    answer = ask(operation, client, body, **named)
    assert answer.ok, f"{operation.__name__.rsplit('.', 1)[-1]} answered {answer.status}: {answer.text}"
    return answer.body


KNOWN: dict[str, Any] = {}


def operator():
    if "operator" not in KNOWN:
        KNOWN["operator"] = signin.signed_in(PLATFORM_URL)
    return KNOWN["operator"]


def operator_id() -> int:
    if "operator_id" not in KNOWN:
        user, _ = signin.account()
        KNOWN["operator_id"] = next(row["id"] for row in done(staff_users, operator()) if row["username"] == user)
    return KNOWN["operator_id"]


def objective_keys(wargame: str) -> list[str]:
    declared = yaml.safe_load((WARGAMES / wargame / "objectives.yaml").read_text(encoding="utf-8")) or {}
    return [tier["key"] for tier in declared.get("tiers") or []]


def declared_cases(wargame: str) -> list[dict]:
    return yaml.safe_load((CASES / f"{wargame}.yaml").read_text(encoding="utf-8")) or []


def declared_rules() -> str:
    return DECLARED_RULES.read_text()


@dataclass(frozen=True)
class Setup:
    wargame: str
    title: str
    side: str = "defence"
    matchups: tuple[str, ...] = ("def_vs_bot",)
    hp: dict = field(default_factory=lambda: dict(HP))
    suricata_rules: str = ""
    crs_tuning: dict = field(default_factory=lambda: dict(DETECT_WITHOUT_BLOCKING_SEARCH))
    probe_cases: tuple[str, ...] = ()


def round_document(setup: Setup) -> dict:
    posture = f"posture for {setup.title}"
    return {
        "problem": {"kind": "round", "wargame": setup.wargame, "side": setup.side, "title": setup.title,
                    "summary": "Live acceptance round", "body": "Driven by test/ through the generated client",
                    "published": False},
        "steps": [],
        "round": {"matchups": list(setup.matchups), "posture": posture, "probe_cases": list(setup.probe_cases),
                  "objectives": objective_keys(setup.wargame), "hp": setup.hp, "traffic": None,
                  "benign_every_s": BENIGN_EVERY_S, "time_limit_s": None},
        "start_posture": {"name": posture, "suricata_rules": setup.suricata_rules or declared_rules(),
                          "crs_tuning": setup.crs_tuning},
    }


def acceptance_setup(wargame: str) -> Setup:
    return Setup(wargame=wargame, title=TITLE.format(wargame=wargame))


def problem_of(setup: Setup) -> int:
    key = f"problem:{setup.wargame}:{setup.title}"
    if key in KNOWN:
        return KNOWN[key]
    document = round_document(setup)
    standing = next((row for row in done(staff_problems, operator())
                     if row["title"] == setup.title and row["wargame"] == setup.wargame), None)
    if standing is None:
        KNOWN[key] = done(staff_problem_create, operator(), document)["problem"]["id"]
        return KNOWN[key]
    revision = done(staff_problem, operator(), problem_id=standing["id"])["problem"]["revision"]
    done(staff_problem_update, operator(), {**document, "base_revision": revision}, problem_id=standing["id"])
    KNOWN[key] = standing["id"]
    return KNOWN[key]


def acceptance_problem(wargame: str) -> int:
    return problem_of(acceptance_setup(wargame))


def slots() -> list[dict]:
    try:
        answer = ask(staff_range, operator())
    except (httpx2.HTTPError, signin.Refused):
        return []
    return answer.body["slots"] if answer.ok else []


def open_rounds() -> list[dict]:
    answer = ask(round_list, operator(), state=RoundListState.OPEN)
    return answer.body if answer.ok else []


def retry_after(answer: Answer) -> float:
    for item in (answer.body or {}).get("errors") or []:
        waited = (item.get("params") or {}).get("retry_after")
        if isinstance(waited, (int, float)):
            return float(waited)
    return float(POLL)


@dataclass
class Played:
    lease: int
    round: int
    wargame: str
    attack: Any
    slot: int | None = None
    defence: Any = None
    setup: Setup | None = None
    matchup: str = "def_vs_bot"
    closed: bool = False
    stopped: threading.Event = field(default_factory=threading.Event)


OPENED: list[Played] = []
LISTENERS: list[Callable[[Played], None]] = []


def opened_lease(wargame: str, wait: float = ROOM_WAIT) -> dict:
    deadline = time.monotonic() + wait
    while True:
        answer = ask(lease_open, operator(), {"wargame": wargame})
        if answer.status == 201:
            return answer.body
        assert refused_for_room(answer.status, answer.codes) and time.monotonic() < deadline, (
            f"could not open a lease on {wargame}: {answer.status} {answer.text}")
        time.sleep(min(retry_after(answer), 30.0))


def kept_alive(played: Played) -> None:
    def beat() -> None:
        while not played.stopped.wait(HEARTBEAT_EVERY):
            try:
                ask(lease_heartbeat, operator(), lease_id=played.lease)
            except httpx2.HTTPError:
                continue

    threading.Thread(target=beat, name=f"lease-{played.lease}-heartbeat", daemon=True).start()


def seats_for(matchup: str) -> dict:
    human = {"user": operator_id()}
    bot = {"bot": {"name": BOT}}
    return {"def_vs_bot": {"attack": bot, "defence": human},
            "atk_vs_bot": {"attack": human, "defence": bot}}[matchup]


def next_round(played: Played) -> None:
    setup = played.setup or acceptance_setup(played.wargame)
    made = done(round_create, operator(), {
        "problem": problem_of(setup), "matchup": played.matchup, "seats": seats_for(played.matchup),
    }, lease_id=played.lease)
    done(round_start, operator(), round_id=made["round"])
    tokens = made.get("bot_tokens") or {}
    played.round = made["round"]
    played.attack = signin.seated(PLATFORM_URL, tokens["attack"]) if "attack" in tokens else operator()
    played.defence = signin.seated(PLATFORM_URL, tokens["defence"]) if "defence" in tokens else operator()


def play(wargame: str = "board", setup: Setup | None = None, matchup: str = "def_vs_bot") -> Played:
    lease = opened_lease(wargame)
    played = Played(lease=lease["lease"], round=0, wargame=wargame, attack=None, slot=lease.get("slot"),
                    setup=setup, matchup=matchup)
    OPENED.append(played)
    kept_alive(played)
    for listener in LISTENERS:
        listener(played)
    next_round(played)
    return played


def replay(played: Played) -> Played:
    end(played)
    next_round(played)
    return played


def end(played: Played) -> Answer:
    return ask(round_end, operator(), round_id=played.round)


def close(played: Played) -> Answer:
    if played.closed:
        return Answer(200, {"closed": None})
    end(played)
    closed = ask(lease_close, operator(), lease_id=played.lease)
    if closed.ok or "lease_closed" in closed.codes:
        played.closed = True
        played.stopped.set()
    return closed


class Round:
    def __init__(self, wargame: str = "board", setup: Setup | None = None, matchup: str = "def_vs_bot"):
        self.wargame = wargame
        self.setup = setup
        self.matchup = matchup
        self.played: Played | None = None

    def __enter__(self) -> Played:
        self.played = play(self.wargame, self.setup, self.matchup)
        return self.played

    def __exit__(self, *raised) -> None:
        close(self.played)


def fire(played: Played, case: str) -> Answer:
    return ask(attack_fire_case, played.attack, {"case": case}, round_id=played.round)


def fired(played: Played, case: str, wait: float = TOOL_WAIT) -> dict:
    answer = fire(played, case)
    assert answer.status == 202, f"firing {case} answered {answer.status}: {answer.text}"
    if answer.body.get("run") is not None:
        finished_run(played, answer.body["run"], wait)
    return answer.body


def finished_run(played: Played, run: int, wait: float = TOOL_WAIT) -> dict:
    deadline, after, output = time.monotonic() + wait, 0, ""
    while True:
        page = done(attack_tool_output, played.attack, round_id=played.round, run_id=run, after=after)
        output, after = output + page["output"], page["offset"]
        if page["done"] or time.monotonic() >= deadline:
            return {**page, "output": output}
        time.sleep(POLL)


def start_tool(played: Played, tool: str, args: list[str]) -> Answer:
    return ask(attack_start_tool, played.attack, {"tool": tool, "args": args}, round_id=played.round)


def tools_listed(played: Played) -> dict:
    return done(attack_tools, played.attack, round_id=played.round)


def send(played: Played, method: str, path: str, **given) -> Answer:
    return ask(attack_send, played.attack, {"method": method, "path": path, **given}, round_id=played.round)


def attack_seen(played: Played) -> dict:
    return done(attack_state, played.attack, round_id=played.round)


def cases_listed(played: Played) -> list[dict]:
    return done(attack_cases, played.attack, round_id=played.round)


def loot(played: Played, value: Any) -> Answer:
    return ask(attack_loot, played.attack, {"value": value}, round_id=played.round)


def next_origin(played: Played) -> dict:
    return done(attack_next_origin, played.attack, round_id=played.round)


def defence_seen(played: Played) -> dict:
    return done(defence_state, played.defence, round_id=played.round)


def alerts(played: Played) -> list[dict]:
    found, after = [], 0
    for _ in range(ALERT_PAGES):
        page = done(defence_alerts, played.defence, round_id=played.round, after=after)
        found += page["alerts"]
        if not page["alerts"] or page["next"] == after:
            return found
        after = page["next"]
    return found


def marked(listed: list[dict], marker: str) -> list[dict]:
    return [alert for alert in listed if alert["request_id"] == marker]


def engines(listed: list[dict], marker: str) -> set[str]:
    return {alert["engine"] for alert in marked(listed, marker)}


def alerts_until(played: Played, until: Callable[[list[dict]], bool], timeout: float = SCORE_WAIT) -> list[dict]:
    deadline = time.monotonic() + timeout
    while True:
        listed = alerts(played)
        if until(listed) or time.monotonic() >= deadline:
            return listed
        time.sleep(POLL)


def ids_rules(played: Played) -> dict:
    return done(defence_ids_rules, played.defence, round_id=played.round)


def check_ids(played: Played, text: str) -> Answer:
    return ask(defence_ids_check, played.defence, {"text": text}, round_id=played.round)


def tested_field(tested: int | None) -> dict:
    return {"tested": tested} if tested is not None else {}


def apply_ids(played: Played, text: str, tested: int | None = None) -> Answer:
    version = ids_rules(played)["version"]
    return ask(defence_ids_apply, played.defence, {"text": text, "base_version": version, **tested_field(tested)},
               round_id=played.round)


def tune_waf(played: Played, posture: dict, tested: int | None = None) -> Answer:
    version = done(defence_waf, played.defence, round_id=played.round)["version"]
    return ask(defence_waf_apply, played.defence,
               {"posture": posture, "base_version": version, **tested_field(tested)}, round_id=played.round)


def rule_test_ids(played: Played, text: str, cases: list[str] | None = None) -> Answer:
    return ask(defence_ids_test, played.defence, {"text": text, **({"cases": cases} if cases else {})},
               round_id=played.round)


def rule_test_waf(played: Played, posture: dict, cases: list[str] | None = None) -> Answer:
    return ask(defence_waf_test, played.defence, {"posture": posture, **({"cases": cases} if cases else {})},
               round_id=played.round)


def ids_versions(played: Played) -> list[dict]:
    return done(defence_ids_versions, played.defence, round_id=played.round)


def waf_versions(played: Played) -> list[dict]:
    return done(defence_waf_versions, played.defence, round_id=played.round)


def probes_listed(played: Played) -> list[dict]:
    return done(defence_probes, played.defence, round_id=played.round)


def traffic(played: Played) -> dict:
    return done(defence_traffic, played.defence, round_id=played.round)


def defence_terminal_grant(played: Played) -> Answer:
    return ask(defence_terminal, played.defence, round_id=played.round)


def waf_posture(played: Played) -> dict:
    return done(defence_waf, played.defence, round_id=played.round)


def disable_rule(played: Played, sid: int, minutes: float, reason: str) -> Answer:
    return ask(defence_ids_disable, played.defence, {"sid": sid, "minutes": minutes, "reason": reason},
               round_id=played.round)


def disabled_rules(played: Played) -> list[dict]:
    return done(defence_ids_disabled, played.defence, round_id=played.round)


def enable_rule(played: Played, sid: int) -> Answer:
    return ask(defence_ids_enable, played.defence, round_id=played.round, sid=sid)


def score(played: Played, correlation: str | None = None, client=None) -> Answer:
    named = {"correlation": RoundScoreCorrelation(correlation)} if correlation else {}
    return ask(round_score, client or operator(), round_id=played.round, **named)


def score_when_ready(played: Played, until: Callable[[dict], bool], timeout: float = SCORE_WAIT,
                     correlation: str | None = None) -> dict:
    deadline, last = time.monotonic() + timeout, {}
    while time.monotonic() < deadline:
        answer = score(played, correlation)
        if answer.ok:
            last = answer.body
            if until(last):
                return last
        time.sleep(POLL)
    assert alerts(played), (
        f"round {played.round} took in no alert at all in {timeout:.0f}s, so nothing was scored and nothing can be "
        f"concluded about the defence. This is a pipeline failure, not a detection failure: check the follower, "
        f"Filebeat and Elasticsearch.")
    assert last, "never got a score back. Check the follower and Elasticsearch."
    return last


def per_case(scored: dict) -> dict[str, dict]:
    return {line["case"]: line for line in scored["outcomes"]["per_case"]}


def totals(scored: dict) -> dict:
    return scored["outcomes"]["totals"]


def events(played: Played, kinds: set[str] | None = None) -> list[dict]:
    found, after = [], 0
    for _ in range(ALERT_PAGES):
        page = done(round_events, operator(), round_id=played.round, after=after)
        found += [event for event in page["events"] if kinds is None or event["kind"] in kinds]
        if not page["events"] or page["next"] == after:
            return found
        after = page["next"]
    return found


def topology(played: Played) -> dict:
    return done(round_topology, operator(), round_id=played.round)


def round_shown(played: Played, client=None) -> Answer:
    return ask(round_read, client or operator(), round_id=played.round)


def ended_round(played: Played, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        shown = done(round_read, operator(), round_id=played.round)
        if shown["phase"] == "ended" or time.monotonic() >= deadline:
            return shown
        time.sleep(POLL)
