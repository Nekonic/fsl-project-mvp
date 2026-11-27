from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

from django.db import transaction
from django.utils import timezone

from cr import errors
from cr.config import configured
from domain.round_rules import Phase
from domain.types import (
    ACTION_CASE,
    ACTION_ORIGIN_REQUEST,
    CORRELATION_MARKER,
    CORRELATION_WINDOW,
    ActionRecord,
    CommandRecord,
)
from sandbox import access as jump
from sandbox import attacker as box
from sandbox import customers, edge
from sandbox.reach import allocation_range, range_of
from scoring import losses as referee
from scoring.baseline import LOOT_VERIFIED, objective_model
from telemetry import access as waf_log
from telemetry import events as log
from telemetry.models import AccessCursor
from training.attack import cases as firing
from training.attack import origins, tools
from training.models import Action, Allocation, Origin, Player, Round, ToolRun

ATTACKER = box.ATTACKER_ROLE
CUSTOMERS = customers.CUSTOMERS_ROLE
PROXY = "proxy"
CASES = "redteam/cases"
REQUEST_TIMEOUT = 30
BODY_LIMIT = 262144
SELF_MARKING_TOOLS = ("curl", "sqlmap")
STOPPED_EXIT = 143
TOOL_ARGS_SCHEMA = {"type": "array", "maxItems": tools.MOST_ARGS,
                    "items": {"type": "string", "maxLength": tools.LONGEST_ARG}}
HEADER_NAME = re.compile(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+")
SET_BY_PLATFORM = {tools.MARKER_HEADER.lower(), "host", "content-length"}
REQUEST_METHODS = tools.REQUEST_METHODS
MOST_ARGS = tools.MOST_ARGS
LONGEST_ARG = tools.LONGEST_ARG


@dataclass(frozen=True)
class Brief:
    title: str
    summary: str
    body: str


@dataclass(frozen=True)
class Target:
    public_url: str
    hosts: tuple[str, ...]


@dataclass(frozen=True)
class ObjectiveLine:
    key: str
    name: str
    state: str


@dataclass(frozen=True)
class State:
    round: int
    matchup: str
    phase: str
    started: datetime | None
    ends_at: datetime | None
    end_reason: str
    brief: Brief
    target: Target
    objectives: tuple[ObjectiveLine, ...]
    origins: tuple[origins.OriginLine, ...]
    remaining: origins.Remaining
    takes_loot: bool


@dataclass(frozen=True)
class LastFired:
    at: datetime
    status: int | None
    run: int | None
    running: bool
    exit_code: int | None


@dataclass(frozen=True)
class CaseEntry:
    case: str
    kind: str
    malicious: bool
    title: str
    last: LastFired | None = None


@dataclass(frozen=True)
class Sent:
    action: int | None
    marker: str
    status: int
    headers: tuple[tuple[str, str], ...]
    body: str
    truncated: bool
    source_ip: str
    started: datetime
    ended: datetime


@dataclass(frozen=True)
class Fired:
    action: int
    run: int | None
    status: int | None
    marker: str


@dataclass(frozen=True)
class CustomerSent:
    case: str
    marker: str
    status: int
    source_ip: str
    method: str
    path: str
    started: datetime
    ended: datetime


@dataclass(frozen=True)
class ToolSpec:
    tool: str
    args_schema: dict


@dataclass(frozen=True)
class RunLine:
    run: int
    tool: str
    started: datetime
    ended: datetime | None
    exit_code: int | None
    stopped_by: str | None


@dataclass(frozen=True)
class Tools:
    tools: tuple[ToolSpec, ...]
    runs: tuple[RunLine, ...]


@dataclass(frozen=True)
class Started:
    run: int
    action: int


@dataclass(frozen=True)
class RunPage:
    output: str
    offset: int
    done: bool
    exit_code: int | None
    stopped_by: str | None


@dataclass(frozen=True)
class LostObjective:
    key: str
    name: str


@dataclass(frozen=True)
class Looted:
    lost: bool
    objective: LostObjective | None
    objectives: tuple[LostObjective, ...] = ()


@dataclass(frozen=True)
class Ssh:
    host: str
    port: int
    user: str
    private_key: str
    expires_at: datetime | None
    target_host: str
    target_user: str


@dataclass(frozen=True)
class Terminal:
    ws_url: str
    ssh: Ssh


def new_marker() -> str:
    return uuid.uuid4().hex


def phase_allows_writes(found: Round) -> None:
    if found.phase in (Phase.CREATED.value, Phase.STARTING.value):
        raise errors.Conflict(code="round_not_started")
    if found.phase == Phase.ENDED.value:
        raise errors.Conflict(code="round_closed")


def writable(found: Round) -> None:
    phase_allows_writes(found)
    origins.allow_writes(found)


def spend(found: Round, fallen: Sequence[Origin], reached=None) -> None:
    if not fallen:
        return
    reached = reached or range_of(found)
    refused = origins.cut(found, fallen, reached)
    stop_runs(found, "origin_spent", reached)
    if refused:
        raise refused[0]


def spend_from_log(found: Round) -> int:
    fallen = origins.spent_by_log(found)
    spend(found, fallen)
    return len(fallen)


def next_origin(found: Round, player: Player) -> origins.Remaining:
    writable(found)
    given_up = origins.give_up(found, origins.wearing(found))
    if given_up is not None:
        spend(found, [given_up])
    return origins.remaining(found)


def remaining(found: Round) -> origins.Remaining:
    return origins.remaining(found)


def target_url(found: Round, path: str, query: Mapping[str, str] | None = None) -> str:
    found_at = urlsplit(configured().box.target_url)
    joined = f"{found_at.scheme}://{found_at.netloc}{path}"
    if query:
        joined += ("&" if "?" in path else "?") + urlencode(dict(query))
    return joined


def host_of(found: Round, host: str | None) -> str:
    hosts = list(found.snapshot["wargame"]["hosts"])
    if host is None:
        return hosts[0]
    if host not in hosts:
        raise errors.Invalid(code="invalid_choice", path="host")
    return host


def checked_path(path: str) -> str:
    if not isinstance(path, str) or not path.startswith("/") or any(ord(char) <= 0x20 or ord(char) == 0x7F
                                                                     for char in path):
        raise errors.Invalid(code="invalid", path="path")
    return path


def checked_headers(given: Mapping[str, str] | None) -> dict[str, str]:
    kept = {}
    for name, value in dict(given or {}).items():
        if not HEADER_NAME.fullmatch(str(name)):
            raise errors.Invalid(code="invalid", path=f"headers.{name}")
        if any(char in str(value) for char in "\r\n\0"):
            raise errors.Invalid(code="invalid", path=f"headers.{name}")
        if name.lower() not in SET_BY_PLATFORM:
            kept[name] = str(value)
    return kept


def sent_over(runner, method: str, url: str, headers: dict[str, str], body: str | None,
              interface: str = "", as_customer: bool = False):
    argv = tools.request_argv(method, url, headers, body is not None, REQUEST_TIMEOUT, interface)
    command = customers.as_customer(argv) if as_customer else argv
    started = timezone.now()
    ran = runner(command, stdin=body, timeout=REQUEST_TIMEOUT + 10)
    answer = tools.answered(ran.output)
    if not answer.status:
        refused = customers.CustomersUnavailable if as_customer else box.AttackerUnavailable
        raise refused(f"the request never reached the target from the box: {ran.output[-200:]}")
    return answer, started, timezone.now()


def send(found: Round, player: Player, method: str, path: str, host: str | None = None,
         query: Mapping[str, str] | None = None, headers: Mapping[str, str] | None = None,
         body: str | None = None, kind: str = "request") -> Sent:
    writable(found)
    worn = origins.wearing(found)
    reached = range_of(found)
    chosen, marker = host_of(found, host), new_marker()
    path = checked_path(path)
    kept = checked_headers(headers)
    given = {**kept, "Host": chosen, tools.MARKER_HEADER: marker}
    answer, started, ended = sent_over(reached.runner(ATTACKER), method, target_url(found, path, query), given, body)
    action = Action.objects.create(round=found, player=player, kind=kind, marker=marker, correlation=CORRELATION_MARKER,
                                   source_ip=worn.ip, started=started, ended=ended,
                                   meta={"method": method, "path": path, "host": chosen, "status": answer.status,
                                         "query": dict(query or {}), "headers": kept, "body": body})
    log.append(found.pk, "action.sent", {"action": action.pk, "kind": kind, "status": answer.status},
               player_side="attack")
    return Sent(action=action.pk, marker=marker, status=answer.status, headers=answer.headers,
                body=answer.body[:BODY_LIMIT], truncated=len(answer.body) > BODY_LIMIT, source_ip=worn.ip,
                started=started, ended=ended)


def send_as_customer(found: Round, source_ip: str, method: str, path: str, host: str | None = None,
                     query: Mapping[str, str] | None = None, headers: Mapping[str, str] | None = None,
                     body: str | None = None, marker: str | None = None) -> Sent:
    if source_ip in origins.attack_ips(found):
        raise errors.Invalid(code="invalid", path="source_ip")
    reached = range_of(found)
    chosen, marker = host_of(found, host), marker or new_marker()
    given = {**checked_headers(headers), "Host": chosen, tools.MARKER_HEADER: marker}
    answer, started, ended = sent_over(reached.runner(CUSTOMERS), method, target_url(found, checked_path(path), query),
                                       given, body, interface=source_ip, as_customer=True)
    return Sent(action=None, marker=marker, status=answer.status, headers=answer.headers,
                body=answer.body[:BODY_LIMIT], truncated=len(answer.body) > BODY_LIMIT, source_ip=source_ip,
                started=started, ended=ended)


def case_file(found: Round) -> Path:
    return Path(configured().range.source) / CASES / found.snapshot["wargame"]["case_file"]


def declared_cases(found: Round) -> list[dict[str, Any]]:
    return firing.load_cases(case_file(found))


def last_fired(found: Round) -> dict[str, LastFired]:
    latest: dict[str, LastFired] = {}
    for action in (Action.objects.filter(round=found, kind=ACTION_CASE, malicious=True).select_related("run")
                   .order_by("id")):
        run = getattr(action, "run", None)
        latest[action.case_id] = LastFired(
            at=action.started, status=(action.meta or {}).get("status"), run=run.pk if run else None,
            running=bool(run and run.ended is None), exit_code=run.exit_code if run else None)
    return latest


def catalog(found: Round) -> tuple[CaseEntry, ...]:
    fired = last_fired(found)
    return tuple(CaseEntry(case=case["name"], kind="tool" if tools.is_tool_case(case) else "http", malicious=True,
                           title=str(case.get("title") or case["name"]), last=fired.get(case["name"]))
                 for case in declared_cases(found) if case.get("malicious") is True)


def case_of(found: Round, name: str, malicious: bool) -> dict[str, Any]:
    chosen = next((case for case in declared_cases(found)
                   if case["name"] == name and bool(case.get("malicious")) is malicious), None)
    if chosen is None:
        raise errors.NotFound(code="unknown_case", path="case")
    return chosen


def with_host(case: dict[str, Any], host: str) -> dict[str, Any]:
    spec = dict(case["request"])
    spec["headers"] = {**dict(spec.get("headers") or {}), "Host": host}
    return dict(case, request=spec)


def fire_case(found: Round, player: Player, name: str) -> Fired:
    writable(found)
    case = case_of(found, name, malicious=True)
    worn = origins.wearing(found)
    marker = new_marker()
    if tools.is_tool_case(case):
        argv = tools.tool_argv(dict(case, case_id=marker, correlation=CORRELATION_MARKER),
                               configured().box.target_url, box.SQLMAP_RUNS)
        begun = start_run(found, player, worn, marker, ACTION_CASE, case["tool"], argv, case=case)
        return Fired(action=begun.action, run=begun.run, status=None, marker=marker)
    settings, reached = configured(), range_of(found)
    launch = box.launch_with(reached.launcher(worn.origin_id), settings.box)
    started = timezone.now()
    ran = firing.fire(with_host(case, host_of(found, None)), launch, settings.box.target_url, marker=marker)
    status = tools.status(ran.output)
    action = Action.objects.create(round=found, player=player, kind=ACTION_CASE, case_id=case["name"], malicious=True,
                                   expect=case.get("expect"), marker=marker, correlation=CORRELATION_MARKER,
                                   source_ip=worn.ip, started=started, ended=timezone.now(),
                                   meta={**firing.case_meta(case), "status": status})
    log.append(found.pk, "action.sent", {"action": action.pk, "kind": ACTION_CASE, "status": status},
               player_side="attack")
    return Fired(action=action.pk, run=None, status=status, marker=marker)


def fire_benign(found: Round, name: str, source_ip: str) -> CustomerSent:
    if source_ip in origins.attack_ips(found):
        raise errors.Invalid(code="invalid", path="source_ip")
    case = with_host(case_of(found, name, malicious=False), host_of(found, None))
    reached, marker = range_of(found), new_marker()
    runner = reached.runner(CUSTOMERS)

    def launch(argv: list[str], timeout: float = firing.TOOL_TIMEOUT):
        return runner(customers.as_customer([argv[0], "--interface", source_ip, *argv[1:]]), timeout=timeout)

    started = timezone.now()
    ran = firing.fire(case, launch, configured().box.target_url, marker=marker)
    return CustomerSent(case=name, marker=marker, status=tools.status(ran.output), source_ip=source_ip,
                        method=case["request"].get("method", "GET"), path=case["request"]["path"], started=started,
                        ended=timezone.now())


def tool_list(found: Round) -> Tools:
    runs = ToolRun.objects.filter(action__round=found).order_by("id")
    return Tools(tools=tuple(ToolSpec(tool=tool, args_schema=TOOL_ARGS_SCHEMA) for tool in tools.FREE_TOOLS),
                 runs=tuple(RunLine(run=run.pk, tool=run.tool, started=run.started, ended=run.ended,
                                    exit_code=run.exit_code, stopped_by=run.stopped_by) for run in runs))


def start_run(found: Round, player: Player, worn: Origin, marker: str, kind: str, tool: str, argv: list[str],
              case: Mapping[str, Any] | None = None, correlation: str = CORRELATION_MARKER) -> Started:
    started = timezone.now()
    with transaction.atomic():
        action = Action.objects.create(
            round=found, player=player, kind=kind, case_id=case["name"] if case else None,
            malicious=True if case else None, expect=case.get("expect") if case else None, marker=marker,
            correlation=correlation, source_ip=worn.ip, started=started, ended=started,
            meta={"tool": tool, "args": argv[1:]})
        run = ToolRun.objects.create(action=action, tool=tool, argv=argv, started=started, output_path="")
        run.output_path = f"{box.RUNS}/{run.pk}/output"
        run.save(update_fields=["output_path"])
    try:
        box.start_run(range_of(found).runner(ATTACKER), run.pk, argv)
    except errors.Unavailable:
        finish(run, None, None)
        raise
    log.append(found.pk, "tool.started", {"run": run.pk, "tool": tool}, player_side="attack")
    return Started(run=run.pk, action=action.pk)


def start_tool(found: Round, player: Player, tool: str, args: list[str]) -> Started:
    writable(found)
    marker = new_marker()
    try:
        argv = tools.free_argv(tool, args, marker)
    except ValueError as refused:
        raise errors.Invalid(code="invalid", path="args") from refused
    worn = origins.wearing(found)
    correlation = CORRELATION_MARKER if tool in SELF_MARKING_TOOLS else CORRELATION_WINDOW
    return start_run(found, player, worn, marker, "tool", tool, argv, correlation=correlation)


def run_of(found: Round, run_id: int) -> ToolRun:
    run = ToolRun.objects.select_related("action").filter(pk=run_id, action__round=found).first()
    if run is None:
        raise errors.NotFound(code="unknown_run")
    return run


def finish(run: ToolRun, exit_code: int | None, stopped_by: str | None) -> None:
    ended = timezone.now()
    updated = ToolRun.objects.filter(pk=run.pk, ended=None).update(ended=ended, exit_code=exit_code,
                                                                   stopped_by=stopped_by)
    if not updated:
        return
    Action.objects.filter(pk=run.action_id).update(ended=ended)
    log.append(run.action.round_id, "tool.ended", {"run": run.pk, "exit_code": exit_code, "stopped_by": stopped_by},
               player_side="attack")
    run.refresh_from_db()


def tool_output(found: Round, run_id: int, after: int = 0) -> RunPage:
    run = run_of(found, run_id)
    said = box.run_output(range_of(found).runner(ATTACKER), run.pk, after)
    if said.done and run.ended is None:
        finish(run, said.exit_code, None)
    elif said.done and run.exit_code is None and said.exit_code is not None:
        ToolRun.objects.filter(pk=run.pk).update(exit_code=said.exit_code)
        run.exit_code = said.exit_code
    return RunPage(output=said.output, offset=said.offset, done=said.done or run.ended is not None,
                   exit_code=run.exit_code, stopped_by=run.stopped_by)


def stop_tool(found: Round, player: Player, run_id: int) -> None:
    writable(found)
    run = run_of(found, run_id)
    if run.ended is not None:
        return
    box.stop_run(range_of(found).runner(ATTACKER), run.pk)
    finish(run, STOPPED_EXIT, "player")


def stop_runs(found: Round, reason: str, reached=None) -> int:
    running = list(ToolRun.objects.select_related("action").filter(action__round=found, ended=None))
    if not running:
        return 0
    attacker = (reached or range_of(found)).runner(ATTACKER)
    for run in running:
        box.stop_run(attacker, run.pk)
        finish(run, STOPPED_EXIT, reason)
    return len(running)


def finished_runs(found: Round) -> int:
    running = list(ToolRun.objects.select_related("action").filter(action__round=found, ended=None))
    if not running:
        return 0
    attacker = range_of(found).runner(ATTACKER)
    done = 0
    for run in running:
        try:
            said = box.run_output(attacker, run.pk, limit=0)
        except errors.NotFound:
            continue
        if said.done:
            finish(run, said.exit_code, None)
            done += 1
    return done


def record_of(action: Action) -> ActionRecord:
    return ActionRecord(action_id=str(action.pk), kind=action.kind, marker=action.marker,
                        correlation=action.correlation, source_ip=action.source_ip, started_at=action.started,
                        ended_at=action.ended, case_id=action.case_id, malicious=action.malicious,
                        expect=action.expect, method=action.meta.get("method"), path=action.meta.get("path"))


def origin_record(request: waf_log.OriginRequest) -> ActionRecord:
    return ActionRecord(action_id=request.marker, kind=ACTION_ORIGIN_REQUEST, marker=request.marker,
                        correlation=CORRELATION_WINDOW, source_ip=request.ip, started_at=request.at,
                        ended_at=request.at, method=request.method, path=request.path)


def logged_actions(found: Round) -> tuple[ActionRecord, ...]:
    return tuple(record_of(action) for action in Action.objects.filter(round=found))


def origin_records(found: Round) -> tuple[ActionRecord, ...]:
    return tuple(origin_record(request) for request in waf_log.origin_requests(found))


def actions(found: Round) -> tuple[ActionRecord, ...]:
    return logged_actions(found) + origin_records(found)


def running(found: Round) -> set[str]:
    return {str(pk) for pk in ToolRun.objects.filter(action__round=found, ended=None).values_list("action_id", flat=True)}


def submit_loot(found: Round, player: Player, value: Any) -> Looted:
    writable(found)
    verdict = referee.submit_loot(found, value, logged_actions(found))
    chosen = verdict.objective
    fell = sorted(verdict.fell, key=lambda fallen: fallen.difficulty, reverse=True)
    return Looted(lost=verdict.lost, objective=LostObjective(key=chosen.key, name=chosen.name) if chosen else None,
                  objectives=tuple(LostObjective(key=one.key, name=one.name) for one in fell))


def terminal(found: Round, player: Player) -> Terminal:
    phase_allows_writes(found)
    if not origins.rows(found):
        origins.fill_pool(found)
    settings, reached = configured(), range_of(found)
    access = jump.open_access(player.pk, box.kali_address(reached), reached.runner(ATTACKER), box.LEARNER_ACCOUNT,
                              settings.jump)
    return Terminal(ws_url=f"/vm-terminal/attack/{found.pk}/",
                    ssh=Ssh(host=access.host, port=access.port, user=access.user, private_key=access.private_key,
                            expires_at=found.ends_at or found.allocation.expires_at, target_host=access.target_host,
                            target_user=access.target_user))


def terminal_shell(player: Player) -> tuple[str, str]:
    grant = jump.granted(player.pk, configured().jump)
    if grant is None:
        raise errors.NotAPlayer()
    return grant.address, box.LEARNER_ACCOUNT


def revoke_terminal(found: Round) -> int:
    settings = configured()
    return sum(1 for player in Player.objects.filter(round=found, side="attack")
               if jump.close_access(player.pk, lambda: range_of(found).runner(ATTACKER), box.LEARNER_ACCOUNT,
                                    settings.jump) is not None)


def close(found: Round) -> None:
    try:
        origins.close_edge(found)
    finally:
        stop_runs(found, "round_end")
        revoke_terminal(found)


def commands(found: Round) -> tuple[CommandRecord, ...]:
    if found.started is None:
        return ()
    typed = box.commands(range_of(found).runner(ATTACKER), configured().box)
    return tuple(CommandRecord(at=command.at, line=command.text)
                 for command in box.within(typed, found.started, found.ended))


def read_commands(found: Round) -> int:
    held, _ = AccessCursor.objects.get_or_create(allocation=found.allocation)
    seen = held.cursor.get("commands", {}).get(str(found.pk))
    fresh = [command for command in commands(found) if seen is None or command.at.isoformat() > seen]
    for command in fresh:
        log.append(found.pk, "command.run", {"command": command.line}, player_side="attack")
    if fresh:
        read = {**held.cursor.get("commands", {}), str(found.pk): fresh[-1].at.isoformat()}
        held.cursor = {**held.cursor, "commands": read}
        held.save(update_fields=["cursor"])
    return len(fresh)


def state(found: Round) -> State:
    held = origins.rows(found)
    wargame = found.snapshot["wargame"]
    problem = found.snapshot["problem"] or {"title": wargame["title"], "summary": "", "body": ""}
    return State(
        round=found.pk, matchup=found.matchup, phase=found.phase, started=found.started, ends_at=found.ends_at,
        end_reason=found.end_reason,
        brief=Brief(title=problem["title"], summary=problem["summary"], body=problem["body"]),
        target=Target(public_url=wargame["public_url"], hosts=tuple(wargame["hosts"])),
        objectives=tuple(ObjectiveLine(key=one.key, name=one.name, state=one.state)
                         for one in referee.objectives(found)),
        origins=origins.lines(held), remaining=origins.remaining_of(held),
        takes_loot=objective_model(found) == LOOT_VERIFIED)


@dataclass(frozen=True)
class Probed:
    case: str
    marker: str
    request: dict | None
    status: int
    body: str
    output: str
    source_ip: str
    started: datetime
    ended: datetime


def start_customers(found: Round, plan: Mapping[str, Any]) -> bool:
    return customers.run(range_of(found).runner(CUSTOMERS), json.dumps(dict(plan)))


def stop_customers(found: Round) -> None:
    customers.stop(range_of(found).runner(CUSTOMERS))


def customer_records(found: Round, offset: int, limit: int) -> str:
    return customers.records(range_of(found).runner(CUSTOMERS), offset, limit)


def cases_of(wargame: Mapping[str, Any]) -> list[dict[str, Any]]:
    return firing.load_cases(Path(configured().range.source) / CASES / wargame["case_file"])


def probe_request(prepared, host: str) -> dict:
    found = urlsplit(prepared.url)
    body = prepared.body.decode() if isinstance(prepared.body, bytes) else prepared.body
    headers = {name: value for name, value in prepared.headers.items()
               if name.lower() not in SET_BY_PLATFORM}
    return {"method": prepared.method, "host": host, "path": found.path + (f"?{found.query}" if found.query else ""),
            "headers": headers, **({"body": body} if body is not None else {})}


def fire_probe(allocation: Allocation, wargame: Mapping[str, Any], case: Mapping[str, Any], marker: str) -> Probed:
    settings, reached = configured(), allocation_range(allocation)
    offered = box.find(reached.describe(), None, settings.box)
    edge.admit(reached.runner(settings.edge.role), [offered["source_ip"]], settings.edge)
    box.wear_origin(offered, reached.runner(PROXY))
    started = timezone.now()
    if tools.is_tool_case(dict(case)):
        launch = box.launch_with(reached.launcher(offered["id"]), settings.box)
        ran = firing.fire(dict(case), launch, settings.box.target_url, runs=box.SQLMAP_RUNS, marker=marker)
        return Probed(case=case["name"], marker=marker, request=None, status=0, body="", output=ran.output,
                      source_ip=offered["source_ip"], started=started, ended=timezone.now())
    attacker = reached.runner(ATTACKER)

    def launch(argv: list[str], timeout: float = firing.REQUEST_TIMEOUT):
        return attacker(argv, timeout=timeout)

    host = list(wargame["hosts"])[0]
    hosted = tools.apply_prefetch(with_host(dict(case), host), settings.box.target_url, launch,
                                  firing.REQUEST_TIMEOUT, marker=marker)
    prepared = firing.build_request(hosted, settings.box.target_url, marker=marker)
    request = probe_request(prepared, host)
    answer, started, ended = sent_over(attacker, prepared.method, prepared.url,
                                       {**request["headers"], "Host": host, tools.MARKER_HEADER: marker},
                                       request.get("body"))
    return Probed(case=case["name"], marker=marker, request=request, status=answer.status, body=answer.body,
                  output="", source_ip=offered["source_ip"], started=started, ended=ended)
