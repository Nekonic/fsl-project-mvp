from __future__ import annotations

import json
import os
import secrets
import shlex
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests
import yaml

from bots import rest, signin
from bots import shell as bot_shell
from opening import refused_for_room

REPO_ROOT = Path(__file__).resolve().parent.parent
PLATFORM_URL = os.environ.get("CR_PLATFORM_URL", "http://localhost:8000").rstrip("/")
DECLARED_RULES = REPO_ROOT / "deploy/suricata/rules/local.rules"
CASES = REPO_ROOT / "redteam/cases"
WARGAMES = REPO_ROOT / "wargames"
TITLE = "Acceptance {wargame}"
BOT = "acceptance"
CRS_SETUP = "/etc/nginx/modsecurity/crs/crs-setup.conf"
CRS_EXCLUSIONS = "/etc/nginx/modsecurity/crs/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf"
SITE_CONF = "/etc/nginx/defence/board.com.conf"
HTTP_CONF = "/etc/nginx/defence/http.conf"
RULE_ENGINE_OFF = "SecRuleEngine Off\n"
RULE_ENGINE_ON = "SecRuleEngine On\n"
DETECT_WITHOUT_BLOCKING_SEARCH = {
    CRS_EXCLUSIONS: 'SecRule REQUEST_FILENAME "@beginsWith /search/" "id:10001,phase:1,pass,nolog,ctl:ruleRemoveById=949110"\n'}


BOT_SEARCH_RULE = ('SecRule ARGS:q "@contains or 1=1" "id:10099,phase:2,t:none,t:lowercase,deny,status:403,log,'
                   'msg:\'bot rule for SQL injection in search\'"\n')
STATIC_EXCLUDED = 'SecRule REQUEST_FILENAME "@beginsWith /static/" "id:10002,phase:1,pass,nolog,ctl:ruleRemoveById=930130"\n'


def appended_and_reloaded(path: str, text: str) -> str:
    return f"printf %s {shlex.quote(text)} >> {path} && sudo nginx -t && sudo nginx -s reload"


def paranoia(level: int, inbound: int | None = None) -> str:
    lines = (f'SecAction "id:900000,phase:1,pass,t:none,nolog,setvar:tx.blocking_paranoia_level={level}"\n'
             f'SecAction "id:900001,phase:1,pass,t:none,nolog,setvar:tx.detection_paranoia_level={level}"\n')
    if inbound:
        lines += f'SecAction "id:900110,phase:1,pass,t:none,nolog,setvar:tx.inbound_anomaly_score_threshold={inbound}"\n'
    return lines


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


def ask(operation: str, client, body: dict | None = None, **named) -> Answer:
    answered = rest.request(client, operation, body=body, **named)
    parsed = json.loads(answered.content) if answered.content else None
    return Answer(int(answered.status_code), parsed, dict(answered.headers))


def done(operation, client, body: dict | None = None, **named) -> Any:
    answer = ask(operation, client, body, **named)
    assert answer.ok, f"{operation} answered {answer.status}: {answer.text}"
    return answer.body


KNOWN: dict[str, Any] = {}


def operator():
    if "operator" not in KNOWN:
        KNOWN["operator"] = signin.signed_in(PLATFORM_URL)
    return KNOWN["operator"]


def operator_username() -> str:
    user, _ = signin.account()
    return user


def objective_keys(wargame: str) -> list[str]:
    declared = yaml.safe_load((WARGAMES / wargame / "objectives.yaml").read_text(encoding="utf-8")) or {}
    return [tier["key"] for tier in declared.get("tiers") or []]


def objective_difficulties(wargame: str) -> dict[str, int]:
    declared = yaml.safe_load((WARGAMES / wargame / "objectives.yaml").read_text(encoding="utf-8")) or {}
    return {tier["key"]: int(tier["difficulty"]) for tier in declared.get("tiers") or []}


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
    suricata_rules: str = ""
    waf_files: dict = field(default_factory=lambda: dict(DETECT_WITHOUT_BLOCKING_SEARCH))
    probe_cases: tuple[str, ...] = ()


def round_document(setup: Setup) -> dict:
    posture = f"posture for {setup.title}"
    return {
        "problem": {"kind": "round", "wargame": setup.wargame, "side": setup.side, "title": setup.title,
                    "summary": "Live acceptance round", "body": "Driven by test/ through the schema",
                    "published": False},
        "round": {"matchups": list(setup.matchups), "posture": posture, "probe_cases": list(setup.probe_cases),
                  "objectives": objective_keys(setup.wargame), "traffic": None,
                  "benign_every_s": BENIGN_EVERY_S, "time_limit_s": None},
        "start_posture": {"name": posture, "suricata_rules": setup.suricata_rules or declared_rules(),
                          "waf_files": setup.waf_files},
    }


def acceptance_setup(wargame: str) -> Setup:
    return Setup(wargame=wargame, title=TITLE.format(wargame=wargame))


def problem_of(setup: Setup) -> int:
    key = f"problem:{setup.wargame}:{setup.title}"
    if key in KNOWN:
        return KNOWN[key]
    document = round_document(setup)
    standing = next((row for row in done("staff_problems", operator())
                     if row["title"] == setup.title and row["wargame"] == setup.wargame), None)
    if standing is None:
        KNOWN[key] = done("staff_problem_create", operator(), document)["problem"]["id"]
        return KNOWN[key]
    revision = done("staff_problem", operator(), problem_id=standing["id"])["problem"]["revision"]
    done("staff_problem_update", operator(), {**document, "base_revision": revision}, problem_id=standing["id"])
    KNOWN[key] = standing["id"]
    return KNOWN[key]


def acceptance_problem(wargame: str) -> int:
    return problem_of(acceptance_setup(wargame))


def slots() -> list[dict]:
    try:
        answer = ask("staff_range", operator())
    except (requests.RequestException, signin.Refused):
        return []
    return answer.body["slots"] if answer.ok else []


def open_rounds() -> list[dict]:
    answer = ask("round_list", operator(), state="open")
    return answer.body if answer.ok else []


def retry_after(answer: Answer) -> float:
    for item in (answer.body or {}).get("errors") or []:
        waited = (item.get("params") or {}).get("retry_after")
        if isinstance(waited, (int, float)):
            return float(waited)
    return float(POLL)


@dataclass
class Played:
    allocation: int
    round: int
    wargame: str
    attack: Any
    slot: int | None = None
    defence: Any = None
    setup: Setup | None = None
    matchup: str = "def_vs_bot"
    humans: dict = field(default_factory=dict)
    closed: bool = False
    stopped: threading.Event = field(default_factory=threading.Event)


OPENED: list[Played] = []
LISTENERS: list[Callable[[Played], None]] = []


def opened_allocation(wargame: str, wait: float = ROOM_WAIT) -> dict:
    deadline = time.monotonic() + wait
    while True:
        answer = ask("allocation_open", operator(), {"wargame": wargame})
        if answer.status == 201:
            return answer.body
        assert refused_for_room(answer.status, answer.codes) and time.monotonic() < deadline, (
            f"could not open an allocation on {wargame}: {answer.status} {answer.text}")
        time.sleep(min(retry_after(answer), 30.0))


def kept_alive(played: Played) -> None:
    def beat() -> None:
        while not played.stopped.wait(HEARTBEAT_EVERY):
            try:
                ask("allocation_heartbeat", operator(), allocation_id=played.allocation)
            except requests.RequestException:
                continue

    threading.Thread(target=beat, name=f"allocation-{played.allocation}-heartbeat", daemon=True).start()


def players_for(matchup: str, humans: dict | None = None) -> dict:
    human = {"username": operator_username()}
    bot = {"bot": {"name": BOT}}
    named = {side: {"username": username} for side, (username, _) in (humans or {}).items()}
    return {**{"def_vs_bot": {"attack": bot, "defence": human},
               "atk_vs_bot": {"attack": human, "defence": bot},
               "pvp": {"attack": human, "defence": human}}[matchup], **named}


def human_account() -> tuple[str, Any]:
    username, password = f"acceptance-{secrets.token_hex(4)}", secrets.token_urlsafe(24)
    anonymous = signin.anonymous(PLATFORM_URL)
    ask("auth_csrf", anonymous)
    signed_up = ask("auth_signup", anonymous, {"username": username, "password": password})
    assert signed_up.status == 201, f"could not sign up {username}: {signed_up.text}"
    done("staff_user_approve", operator(), username=username)
    session = signin.anonymous(PLATFORM_URL)
    ask("auth_csrf", session)
    done("auth_login", session, {"username": username, "password": password})
    return username, session


def account_disabled(username: str) -> Answer:
    return ask("staff_user_disable", operator(), username=username)


def next_round(played: Played) -> None:
    setup = played.setup or acceptance_setup(played.wargame)
    made = done("round_create", operator(), {
        "problem": problem_of(setup), "matchup": played.matchup, "players": players_for(played.matchup, played.humans),
    }, allocation_id=played.allocation)
    done("round_start", operator(), round_id=made["round"])
    tokens = made.get("bot_tokens") or {}
    played.round = made["round"]
    humans = {side: client for side, (_, client) in played.humans.items()}
    played.attack = signin.playing(PLATFORM_URL, tokens["attack"]) if "attack" in tokens else humans.get("attack", operator())
    played.defence = (signin.playing(PLATFORM_URL, tokens["defence"]) if "defence" in tokens
                      else humans.get("defence", operator()))


def play(wargame: str = "board", setup: Setup | None = None, matchup: str = "def_vs_bot",
         humans: dict | None = None) -> Played:
    allocation = opened_allocation(wargame)
    played = Played(allocation=allocation["allocation"], round=0, wargame=wargame, attack=None, slot=allocation.get("slot"),
                    setup=setup, matchup=matchup, humans=dict(humans or {}))
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
    return ask("round_end", operator(), round_id=played.round)


def close(played: Played) -> Answer:
    if played.closed:
        return Answer(200, {"closed": None})
    end(played)
    closed = ask("allocation_close", operator(), allocation_id=played.allocation)
    if closed.ok or "allocation_closed" in closed.codes:
        played.closed = True
        played.stopped.set()
    return closed


class Round:
    def __init__(self, wargame: str = "board", setup: Setup | None = None, matchup: str = "def_vs_bot",
                 humans: dict | None = None):
        self.wargame = wargame
        self.setup = setup
        self.matchup = matchup
        self.humans = humans
        self.played: Played | None = None

    def __enter__(self) -> Played:
        self.played = play(self.wargame, self.setup, self.matchup, self.humans)
        return self.played

    def __exit__(self, *raised) -> None:
        close(self.played)


def fire(played: Played, case: str) -> Answer:
    return ask("attack_fire_case", played.attack, {"case": case}, round_id=played.round)


def fired(played: Played, case: str, wait: float = TOOL_WAIT) -> dict:
    answer = fire(played, case)
    assert answer.status == 202, f"firing {case} answered {answer.status}: {answer.text}"
    if answer.body.get("run") is not None:
        finished_run(played, answer.body["run"], wait)
    return answer.body


def finished_run(played: Played, run: int, wait: float = TOOL_WAIT) -> dict:
    deadline, after, output = time.monotonic() + wait, 0, ""
    while True:
        page = done("attack_tool_output", played.attack, round_id=played.round, run_id=run, after=after)
        output, after = output + page["output"], page["offset"]
        if page["done"] or time.monotonic() >= deadline:
            return {**page, "output": output}
        time.sleep(POLL)


def start_tool(played: Played, tool: str, args: list[str]) -> Answer:
    return ask("attack_start_tool", played.attack, {"tool": tool, "args": args}, round_id=played.round)


def tools_listed(played: Played) -> dict:
    return done("attack_tools", played.attack, round_id=played.round)


def send(played: Played, method: str, path: str, **given) -> Answer:
    return ask("attack_send", played.attack, {"method": method, "path": path, **given}, round_id=played.round)


def attack_seen(played: Played) -> dict:
    return done("attack_state", played.attack, round_id=played.round)


def cases_listed(played: Played) -> list[dict]:
    return done("attack_cases", played.attack, round_id=played.round)


def loot(played: Played, value: Any) -> Answer:
    return ask("attack_loot", played.attack, {"value": value}, round_id=played.round)


def next_origin(played: Played) -> dict:
    return done("attack_next_origin", played.attack, round_id=played.round)


def defence_seen(played: Played) -> dict:
    return done("defence_state", played.defence, round_id=played.round)


def alerts(played: Played) -> list[dict]:
    found, after = [], 0
    for _ in range(ALERT_PAGES):
        page = done("defence_alerts", played.defence, round_id=played.round, after=after)
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
    return done("defence_ids_rules", played.defence, round_id=played.round)


def sensor_device(wargame: str) -> dict:
    devices = yaml.safe_load((WARGAMES / wargame / "topology.yaml").read_text())["devices"]
    return next(device for device in devices.values() if "sensor" in (device.get("roles") or []))


def ids_written_and_reloaded(wargame: str, text: str) -> str:
    sensor = sensor_device(wargame)
    rules = sensor["rules"]
    return (f"cp {rules} ~/previous.rules && printf %s {shlex.quote(text)} > {rules} && sudo suricata -T "
            f"&& sudo {sensor['reload']} || {{ cat ~/previous.rules > {rules}; exit 1; }}")


@dataclass(frozen=True)
class Reloaded:
    shell: dict
    version: dict | None

    @property
    def ok(self) -> bool:
        return bool(self.shell.get("ok")) and self.version is not None

    @property
    def text(self) -> str:
        return json.dumps({"shell": self.shell, "version": self.version})[:2000]


def apply_ids(played: Played, text: str, timeout: float = SCORE_WAIT) -> Reloaded:
    before = ids_rules(played)["version"]
    ran = in_shell(played, "ids", ids_written_and_reloaded(played.wargame, text))
    deadline = time.monotonic() + timeout
    while ran.get("ok"):
        shown = ids_rules(played)
        if shown["recorded"] and shown["version"] > before:
            return Reloaded(ran, max(ids_versions(played), key=lambda one: one["version"]))
        if time.monotonic() >= deadline:
            break
        time.sleep(POLL)
    return Reloaded(ran, None)


def sensor_runs_the_declared_rules(played: Played) -> str:
    live = ids_rules(played)["text"]
    if live != declared_rules():
        return f"the sensor's live rules are not deploy/suricata/rules/local.rules: {live[:300]!r}"
    checked = in_shell(played, "ids", "sudo suricata -T")
    return "ok" if checked.get("ok") else json.dumps(checked)[:2000]


def tested_field(tested: int | None) -> dict:
    return {"tested": tested} if tested is not None else {}


def tune_waf(played: Played, files: dict[str, str], tested: int | None = None) -> Answer:
    version = done("defence_waf", played.defence, round_id=played.round)["version"]
    return ask("defence_waf_apply", played.defence,
               {"files": files, "base_version": version, **tested_field(tested)}, round_id=played.round)


def rule_test_ids(played: Played, text: str, cases: list[str] | None = None) -> Answer:
    return ask("defence_ids_test", played.defence, {"text": text, **({"cases": cases} if cases else {})},
               round_id=played.round)


def rule_test_waf(played: Played, files: dict[str, str], cases: list[str] | None = None) -> Answer:
    return ask("defence_waf_test", played.defence, {"files": files, **({"cases": cases} if cases else {})},
               round_id=played.round)


def ids_versions(played: Played) -> list[dict]:
    return done("defence_ids_versions", played.defence, round_id=played.round)


def waf_versions(played: Played) -> list[dict]:
    return done("defence_waf_versions", played.defence, round_id=played.round)


def probes_listed(played: Played) -> list[dict]:
    return done("defence_probes", played.defence, round_id=played.round)


def traffic(played: Played) -> dict:
    return done("defence_traffic", played.defence, round_id=played.round)


def defence_terminal_grant(played: Played) -> Answer:
    return ask("defence_terminal", played.defence, round_id=played.round)


TERMINALS = {"attack": "attack_terminal", "defence": "defence_terminal", "ids": "defence_ids_terminal"}


def in_shell(played: Played, terminal: str, command: str) -> dict:
    client = played.attack if terminal == "attack" else played.defence

    def grant() -> dict:
        answer = ask(TERMINALS[terminal], client, round_id=played.round)
        return {"ok": answer.ok, "status": answer.status, "body": answer.body}

    return bot_shell.run((played.round, terminal), {"command": command}, grant)


def waf_files(played: Played) -> dict[str, str]:
    return {one["path"]: one["text"] for one in done("defence_waf", played.defence, round_id=played.round)["files"]}


def appended(played: Played, path: str, *lines: str) -> dict[str, str]:
    return {path: waf_files(played)[path].rstrip("\n") + "\n" + "".join(lines)}


def score(played: Played, correlation: str | None = None, client=None) -> Answer:
    named = {"correlation": correlation} if correlation else {}
    return ask("round_score", client or operator(), round_id=played.round, **named)


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
        f"concluded about the defence. This is a pipeline failure, not a detection failure: check the platform log for failed reads, "
        f"Filebeat and Elasticsearch.")
    assert last, "never got a score back. Check the platform log for failed reads and Elasticsearch."
    return last


def per_case(scored: dict) -> dict[str, dict]:
    return {line["case"]: line for line in scored["outcomes"]["per_case"]}


def totals(scored: dict) -> dict:
    return scored["outcomes"]["totals"]


def events(played: Played, kinds: set[str] | None = None) -> list[dict]:
    found, after = [], 0
    for _ in range(ALERT_PAGES):
        page = done("round_events", operator(), round_id=played.round, after=after)
        found += [event for event in page["events"] if kinds is None or event["kind"] in kinds]
        if not page["events"] or page["next"] == after:
            return found
        after = page["next"]
    return found


def topology(played: Played) -> dict:
    return done("round_topology", operator(), round_id=played.round)


def round_shown(played: Played, client=None) -> Answer:
    return ask("round_read", client or operator(), round_id=played.round)


def ended_round(played: Played, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        shown = done("round_read", operator(), round_id=played.round)
        if shown["phase"] == "ended" or time.monotonic() >= deadline:
            return shown
        time.sleep(POLL)
