from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

from django.db import transaction
from django.utils import timezone

from attack import box, firing, tools
from attack.models import AccessCursor, Action, OriginBudget, ToolRun
from cr import config, errors
from domain.ledger import LedgerState
from domain.ledger import debit as ledger_debit
from domain.round_rules import Phase
from domain.types import (
    ACTION_CASE,
    CORRELATION_MARKER,
    CORRELATION_WINDOW,
    ActionRecord,
    Charge,
    CommandRecord,
    HpRule,
    OriginState,
)
from events import log
from ingest import elastic
from match.models import Lease, Round, Seat
from range import edge, jump
from range.substrate import substrate
from referee import service as referee

ATTACKER = box.ATTACKER_ROLE
PROXY = "proxy"
CASES = "redteam/cases"
HP_FIELDS = ("budget", "per_request", "refused_x", "burst_per_s", "burst_x")
LESSON_HP = {"budget": 500, "per_request": 1, "refused_x": 3, "burst_per_s": 10, "burst_x": 2}
REQUEST_TIMEOUT = 30
BODY_LIMIT = 65536
ACCESS_PAGES = 10
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
class Origin:
    id: str
    label: str
    ip: str


@dataclass(frozen=True)
class Hp:
    origin: Origin | None
    left: int
    budget: int
    origins_left: int
    spent: tuple[str, ...]
    rule: HpRule


@dataclass(frozen=True)
class OriginLine:
    id: str
    label: str
    ip: str
    left: int
    budget: int
    spent_at: datetime | None


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
    origins: tuple[OriginLine, ...]
    hp: Hp


@dataclass(frozen=True)
class CaseEntry:
    case: str
    kind: str
    malicious: bool
    title: str


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


def configured() -> config.Config:
    return config.build()


def range_of(found: Round):
    reached = substrate(configured().range)
    if hasattr(reached, "in_slot") and found.lease.slot:
        return reached.in_slot(found.lease.slot)
    return reached


def now() -> datetime:
    return timezone.now()


def new_marker() -> str:
    return uuid.uuid4().hex


def rule_of(found: Round) -> HpRule:
    given = (found.snapshot.get("round") or {}).get("hp") or LESSON_HP
    return HpRule(**{name: int(given[name]) for name in HP_FIELDS})


def budgets(found: Round) -> list[OriginBudget]:
    return list(OriginBudget.objects.filter(round=found))


def current_of(rows: Sequence[OriginBudget]) -> OriginBudget | None:
    return next((row for row in rows if row.spent_at is None), None)


def hp_of(found: Round, rows: Sequence[OriginBudget]) -> Hp:
    rule = rule_of(found)
    worn = current_of(rows)
    return Hp(origin=Origin(id=worn.origin_id, label=worn.label, ip=worn.ip) if worn else None,
              left=worn.left if worn else 0, budget=worn.budget if worn else rule.budget,
              origins_left=sum(1 for row in rows if row.spent_at is None),
              spent=tuple(row.ip for row in rows if row.spent_at is not None), rule=rule)


def hp(found: Round) -> Hp:
    return hp_of(found, budgets(found))


def phase_allows_writes(found: Round) -> None:
    if found.phase in (Phase.CREATED.value, Phase.STARTING.value):
        raise errors.Conflict(code="round_not_started")
    if found.phase == Phase.ENDED.value:
        raise errors.Conflict(code="round_closed")


def origins_allow_writes(found: Round) -> None:
    rows = budgets(found)
    if rows and current_of(rows) is None:
        raise errors.Conflict(code="origins_spent")


def writable(found: Round) -> None:
    phase_allows_writes(found)
    origins_allow_writes(found)


def wearing(found: Round) -> OriginBudget:
    rows = budgets(found)
    if not rows:
        fill_pool(found)
        rows = budgets(found)
    worn = current_of(rows)
    if worn is None:
        raise errors.Conflict(code="origins_spent")
    return worn


def fill_pool(found: Round) -> Hp:
    settings, reached = configured(), range_of(found)
    described = reached.describe()
    offered = sorted(box.origins(described, settings.box), key=lambda origin: (not origin["default"], origin["id"]))
    if not offered:
        raise box.AttackerUnavailable("the attacker box stands on no origin")
    rule = rule_of(found)
    with transaction.atomic():
        for origin in offered:
            OriginBudget.objects.get_or_create(round=found, ip=origin["source_ip"], defaults={
                "origin_id": origin["id"], "label": origin["label"], "budget": rule.budget, "left": rule.budget})
        AccessCursor.objects.get_or_create(lease=found.lease)
    refill_edge(found, reached, described, afresh=True)
    worn = current_of(budgets(found))
    if worn is not None:
        box.wear_origin({"source_ip": worn.ip}, reached.runner(PROXY))
    return hp(found)


def customer_origins(found: Round, reached=None, described=None) -> list[dict]:
    settings = configured()
    reached = reached or range_of(found)
    described = described or reached.describe()
    unbound = box.unbound_source(reached.runner(ATTACKER), settings.box)
    return box.customer_origins(described, settings.box, unbound)


def customer_addresses(found: Round, reached=None, described=None) -> list[str]:
    return [address for origin in customer_origins(found, reached, described) for address in origin["addresses"]]


def refill_edge(found: Round, reached=None, described=None, afresh: bool = False) -> None:
    settings = configured()
    reached = reached or range_of(found)
    rows = budgets(found)
    if not rows:
        return
    pool = [row.ip for row in rows] + customer_addresses(found, reached, described)
    spent = [row.ip for row in rows if row.spent_at is not None]
    filled = edge.restart if afresh else edge.refill
    filled(reached.runner(settings.edge.role), pool, spent, settings.edge)


def state_of(row: OriginBudget) -> OriginState:
    return OriginState(origin_id=row.origin_id, ip=row.ip, label=row.label, budget=row.budget, left=row.left,
                       spent_at=row.spent_at)


def debit(found: Round, charges: Sequence[Charge],
          charged_markers: Iterable[str] = ()) -> tuple[list[OriginBudget], dict[str, int]]:
    rows = list(OriginBudget.objects.select_for_update().filter(round=found))
    state = LedgerState(origins=tuple(state_of(row) for row in rows),
                        per_second=tuple((row.ip, int(second), int(n)) for row in rows for second, n in row.recent),
                        charged_markers=frozenset(charged_markers))
    moved, newly_spent = ledger_debit(state, charges, rule_of(found))
    after = {origin.ip: origin for origin in moved.origins}
    recent: dict[str, list[list[int]]] = {}
    for ip, second, n in moved.per_second:
        recent.setdefault(ip, []).append([second, n])
    charged: dict[str, int] = {}
    for row in rows:
        origin = after[row.ip]
        if row.left != origin.left:
            charged[row.ip] = row.left - origin.left
        row.left, row.spent_at, row.recent = origin.left, origin.spent_at, recent.get(row.ip, [])
        row.save(update_fields=["left", "spent_at", "recent"])
    fallen = {origin.ip for origin in newly_spent}
    return [row for row in rows if row.ip in fallen], charged


def report_charges(found: Round, charged: Mapping[str, int]) -> None:
    left = {row.ip: row.left for row in budgets(found)}
    for ip, amount in sorted(charged.items()):
        log.append(found.pk, "origin.charged", {"ip": ip, "charged": amount, "left": left[ip]}, seat_side="attack")


def spend(found: Round, fallen: Sequence[OriginBudget], reached=None) -> None:
    if not fallen:
        return
    settings = configured()
    reached = reached or range_of(found)
    for row in fallen:
        log.append(found.pk, "origin.spent", {"ip": row.ip}, seat_side="attack")
    router = reached.runner(settings.edge.role)
    refused: list[errors.Unavailable] = []
    for row in fallen:
        try:
            edge.spend(router, row.ip, settings.edge)
        except errors.Unavailable as failed:
            refused.append(failed)
    stop_runs(found, "origin_spent", reached)
    following = current_of(budgets(found))
    if following is None:
        log.append(found.pk, "origins.spent", {}, seat_side="attack")
    else:
        box.wear_origin({"source_ip": following.ip}, reached.runner(PROXY))
        log.append(found.pk, "origin.switched", {"ip": following.ip}, seat_side="attack")
    if refused:
        raise refused[0]


def charge_sent(found: Round, action: Action, status: int, reached=None) -> None:
    rule = rule_of(found)
    with transaction.atomic():
        fallen, charged = debit(found, [Charge(origin_ip=action.source_ip, at=action.ended,
                                               refused=rule.refuses(status), marker=action.marker,
                                               synchronous=True)])
    report_charges(found, charged)
    spend(found, fallen, reached)


def next_origin(found: Round, seat: Seat) -> Hp:
    writable(found)
    worn = wearing(found)
    with transaction.atomic():
        given_up = OriginBudget.objects.select_for_update().filter(pk=worn.pk, spent_at=None).update(spent_at=now())
    if given_up:
        spend(found, [OriginBudget.objects.get(pk=worn.pk)])
    return hp(found)


def charge_access_page(found: Round, held: AccessCursor, cursor, ips: set[str], rule: HpRule):
    settings = configured()
    records, moved = elastic.access_events(settings.elastic.url, settings.elastic.index_of(found.lease.slot), cursor)
    charges = [Charge(origin_ip=record["source_ip"], at=record["at"], refused=rule.refuses(record["status"]),
                      marker=record["marker"])
               for record in records if record["source_ip"] in ips and record["at"] is not None
               and (found.started is None or record["at"] >= found.started)]
    markers = {charge.marker for charge in charges if charge.marker}
    synced = Action.objects.filter(round=found, charged=True, marker__in=markers).values_list("marker", flat=True)
    with transaction.atomic():
        fallen, charged = debit(found, charges, set(synced))
        held.cursor = {**held.cursor, "access": moved}
        held.save(update_fields=["cursor"])
    return moved, charged, fallen


def charge_from_access(found: Round) -> dict[str, int]:
    rows = budgets(found)
    if not rows:
        return {}
    rule, ips = rule_of(found), {row.ip for row in rows}
    held, _ = AccessCursor.objects.get_or_create(lease=found.lease)
    cursor = held.cursor.get("access")
    total: dict[str, int] = {}
    try:
        for _ in range(ACCESS_PAGES):
            moved, charged, fallen = charge_access_page(found, held, cursor, ips, rule)
            for ip, amount in charged.items():
                total[ip] = total.get(ip, 0) + amount
            spend(found, fallen)
            if moved == cursor:
                break
            cursor = moved
    finally:
        report_charges(found, total)
    return total


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
    command = box.as_customer_command(argv) if as_customer else argv
    started = now()
    ran = runner(command, stdin=body, timeout=REQUEST_TIMEOUT + 10)
    answer = tools.answered(ran.output)
    if not answer.status:
        raise box.AttackerUnavailable(f"the request never reached the target from the box: {ran.output[-200:]}")
    return answer, started, now()


def send(found: Round, seat: Seat, method: str, path: str, host: str | None = None,
         query: Mapping[str, str] | None = None, headers: Mapping[str, str] | None = None,
         body: str | None = None, kind: str = "request") -> Sent:
    writable(found)
    worn = wearing(found)
    reached = range_of(found)
    chosen, marker = host_of(found, host), new_marker()
    path = checked_path(path)
    given = {**checked_headers(headers), "Host": chosen, tools.MARKER_HEADER: marker}
    answer, started, ended = sent_over(reached.runner(ATTACKER), method, target_url(found, path, query), given, body)
    action = Action.objects.create(round=found, seat=seat, kind=kind, marker=marker, correlation=CORRELATION_MARKER,
                                   source_ip=worn.ip, started=started, ended=ended, charged=True,
                                   meta={"method": method, "path": path, "host": chosen, "status": answer.status})
    log.append(found.pk, "action.sent", {"action": action.pk, "kind": kind, "status": answer.status},
               seat_side="attack")
    charge_sent(found, action, answer.status, reached)
    return Sent(action=action.pk, marker=marker, status=answer.status, headers=answer.headers,
                body=answer.body[:BODY_LIMIT], truncated=len(answer.body) > BODY_LIMIT, source_ip=worn.ip,
                started=started, ended=ended)


def send_as_customer(found: Round, source_ip: str, method: str, path: str, host: str | None = None,
                     query: Mapping[str, str] | None = None, headers: Mapping[str, str] | None = None,
                     body: str | None = None, marker: str | None = None) -> Sent:
    if source_ip in {row.ip for row in budgets(found)}:
        raise errors.Invalid(code="invalid", path="source_ip")
    reached = range_of(found)
    chosen, marker = host_of(found, host), marker or new_marker()
    given = {**checked_headers(headers), "Host": chosen, tools.MARKER_HEADER: marker}
    answer, started, ended = sent_over(reached.runner(ATTACKER), method, target_url(found, checked_path(path), query),
                                       given, body, interface=source_ip, as_customer=True)
    return Sent(action=None, marker=marker, status=answer.status, headers=answer.headers,
                body=answer.body[:BODY_LIMIT], truncated=len(answer.body) > BODY_LIMIT, source_ip=source_ip,
                started=started, ended=ended)


def case_file(found: Round) -> Path:
    return Path(configured().range.source) / CASES / found.snapshot["wargame"]["case_file"]


def declared_cases(found: Round) -> list[dict[str, Any]]:
    return firing.load_cases(case_file(found))


def catalog(found: Round) -> tuple[CaseEntry, ...]:
    return tuple(CaseEntry(case=case["name"], kind="tool" if tools.is_tool_case(case) else "http", malicious=True,
                           title=str(case.get("title") or case["name"]))
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


def fire_case(found: Round, seat: Seat, name: str) -> Fired:
    writable(found)
    case = case_of(found, name, malicious=True)
    worn = wearing(found)
    marker = new_marker()
    if tools.is_tool_case(case):
        argv = tools.tool_argv(dict(case, case_id=marker, correlation=CORRELATION_MARKER),
                               configured().box.target_url, box.SQLMAP_RUNS)
        begun = start_run(found, seat, worn, marker, ACTION_CASE, case["tool"], argv, case=case)
        return Fired(action=begun.action, run=begun.run, status=None, marker=marker)
    settings, reached = configured(), range_of(found)
    launch = box.launch_with(reached.launcher(worn.origin_id), settings.box)
    started = now()
    ran = firing.fire(with_host(case, host_of(found, None)), launch, settings.box.target_url, marker=marker)
    status = tools.status(ran.output)
    action = Action.objects.create(round=found, seat=seat, kind=ACTION_CASE, case_id=case["name"], malicious=True,
                                   expect=case.get("expect"), marker=marker, correlation=CORRELATION_MARKER,
                                   source_ip=worn.ip, started=started, ended=now(), charged=True,
                                   meta={**firing.case_meta(case), "status": status})
    log.append(found.pk, "action.sent", {"action": action.pk, "kind": ACTION_CASE, "status": status},
               seat_side="attack")
    charge_sent(found, action, status, reached)
    return Fired(action=action.pk, run=None, status=status, marker=marker)


def fire_benign(found: Round, name: str, source_ip: str) -> CustomerSent:
    if source_ip in {row.ip for row in budgets(found)}:
        raise errors.Invalid(code="invalid", path="source_ip")
    case = with_host(case_of(found, name, malicious=False), host_of(found, None))
    reached, marker = range_of(found), new_marker()
    runner = reached.runner(ATTACKER)

    def launch(argv: list[str], timeout: float = firing.TOOL_TIMEOUT):
        return runner(box.as_customer_command([argv[0], "--interface", source_ip, *argv[1:]]), timeout=timeout)

    started = now()
    ran = firing.fire(case, launch, configured().box.target_url, marker=marker)
    return CustomerSent(case=name, marker=marker, status=tools.status(ran.output), source_ip=source_ip,
                        method=case["request"].get("method", "GET"), path=case["request"]["path"], started=started,
                        ended=now())


def tool_list(found: Round) -> Tools:
    runs = ToolRun.objects.filter(action__round=found).order_by("id")
    return Tools(tools=tuple(ToolSpec(tool=tool, args_schema=TOOL_ARGS_SCHEMA) for tool in tools.FREE_TOOLS),
                 runs=tuple(RunLine(run=run.pk, tool=run.tool, started=run.started, ended=run.ended,
                                    exit_code=run.exit_code, stopped_by=run.stopped_by) for run in runs))


def start_run(found: Round, seat: Seat, worn: OriginBudget, marker: str, kind: str, tool: str, argv: list[str],
              case: Mapping[str, Any] | None = None, correlation: str = CORRELATION_MARKER) -> Started:
    started = now()
    with transaction.atomic():
        action = Action.objects.create(
            round=found, seat=seat, kind=kind, case_id=case["name"] if case else None,
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
    log.append(found.pk, "tool.started", {"run": run.pk, "tool": tool}, seat_side="attack")
    return Started(run=run.pk, action=action.pk)


def start_tool(found: Round, seat: Seat, tool: str, args: list[str]) -> Started:
    writable(found)
    marker = new_marker()
    try:
        argv = tools.free_argv(tool, args, marker)
    except ValueError as refused:
        raise errors.Invalid(code="invalid", path="args") from refused
    worn = wearing(found)
    correlation = CORRELATION_MARKER if tool in SELF_MARKING_TOOLS else CORRELATION_WINDOW
    return start_run(found, seat, worn, marker, "tool", tool, argv, correlation=correlation)


def run_of(found: Round, run_id: int) -> ToolRun:
    run = ToolRun.objects.select_related("action").filter(pk=run_id, action__round=found).first()
    if run is None:
        raise errors.NotFound(code="unknown_run")
    return run


def finish(run: ToolRun, exit_code: int | None, stopped_by: str | None) -> None:
    ended = now()
    updated = ToolRun.objects.filter(pk=run.pk, ended=None).update(ended=ended, exit_code=exit_code,
                                                                   stopped_by=stopped_by)
    if not updated:
        return
    Action.objects.filter(pk=run.action_id).update(ended=ended)
    log.append(run.action.round_id, "tool.ended", {"run": run.pk, "exit_code": exit_code, "stopped_by": stopped_by},
               seat_side="attack")
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


def stop_tool(found: Round, seat: Seat, run_id: int) -> None:
    writable(found)
    run = run_of(found, run_id)
    if run.ended is not None:
        return
    box.stop_run(range_of(found).runner(ATTACKER), run.pk)
    finish(run, STOPPED_EXIT, "seat")


def stop_runs(found: Round, reason: str, reached=None) -> int:
    running = list(ToolRun.objects.select_related("action").filter(action__round=found, ended=None))
    if not running:
        return 0
    attacker = (reached or range_of(found)).runner(ATTACKER)
    for run in running:
        box.stop_run(attacker, run.pk)
        finish(run, STOPPED_EXIT, reason)
    return len(running)


def record_of(action: Action) -> ActionRecord:
    return ActionRecord(action_id=str(action.pk), kind=action.kind, marker=action.marker,
                        correlation=action.correlation, source_ip=action.source_ip, started_at=action.started,
                        ended_at=action.ended, case_id=action.case_id, malicious=action.malicious,
                        expect=action.expect, method=action.meta.get("method"), path=action.meta.get("path"))


def actions(found: Round) -> tuple[ActionRecord, ...]:
    return tuple(record_of(action) for action in Action.objects.filter(round=found))


def submit_loot(found: Round, seat: Seat, value: Any) -> Looted:
    writable(found)
    verdict = referee.submit_loot(found, value, actions(found))
    chosen = verdict.objective
    return Looted(lost=verdict.lost, objective=LostObjective(key=chosen.key, name=chosen.name) if chosen else None)


def terminal(found: Round, seat: Seat) -> Terminal:
    phase_allows_writes(found)
    settings, reached = configured(), range_of(found)
    access = jump.open_access(seat.pk, box.kali_address(reached), reached.runner(ATTACKER), box.LEARNER_ACCOUNT,
                              settings.jump)
    return Terminal(ws_url=f"/vm-terminal/attack/{found.pk}/",
                    ssh=Ssh(host=access.host, port=access.port, user=access.user, private_key=access.private_key,
                            expires_at=found.ends_at or found.lease.expires_at, target_host=access.target_host,
                            target_user=access.target_user))


def terminal_shell(seat: Seat) -> tuple[str, str]:
    grant = jump.granted(seat.pk, configured().jump)
    if grant is None:
        raise errors.NotSeated()
    return grant.address, box.LEARNER_ACCOUNT


def revoke_terminal(found: Round) -> int:
    settings = configured()
    return sum(1 for seat in Seat.objects.filter(round=found, side="attack")
               if jump.close_access(seat.pk, lambda: range_of(found).runner(ATTACKER), box.LEARNER_ACCOUNT,
                                    settings.jump) is not None)


def close(found: Round) -> None:
    stop_runs(found, "round_end")
    revoke_terminal(found)


def commands(found: Round) -> tuple[CommandRecord, ...]:
    if found.started is None:
        return ()
    typed = box.commands(range_of(found).runner(ATTACKER), configured().box)
    return tuple(CommandRecord(at=command.at, line=command.text)
                 for command in box.within(typed, found.started, found.ended))


def read_commands(found: Round) -> int:
    held, _ = AccessCursor.objects.get_or_create(lease=found.lease)
    seen = held.cursor.get("commands", {}).get(str(found.pk))
    fresh = [command for command in commands(found) if seen is None or command.at.isoformat() > seen]
    for command in fresh:
        log.append(found.pk, "command.run", {"command": command.line}, seat_side="attack")
    if fresh:
        read = {**held.cursor.get("commands", {}), str(found.pk): fresh[-1].at.isoformat()}
        held.cursor = {**held.cursor, "commands": read}
        held.save(update_fields=["cursor"])
    return len(fresh)


def origin_lines(rows: Sequence[OriginBudget]) -> tuple[OriginLine, ...]:
    return tuple(OriginLine(id=row.origin_id, label=row.label, ip=row.ip, left=row.left, budget=row.budget,
                            spent_at=row.spent_at) for row in rows)


def state(found: Round) -> State:
    rows = budgets(found)
    problem, wargame = found.snapshot["problem"], found.snapshot["wargame"]
    return State(
        round=found.pk, matchup=found.matchup, phase=found.phase, started=found.started, ends_at=found.ends_at,
        end_reason=found.end_reason,
        brief=Brief(title=problem["title"], summary=problem["summary"], body=problem["body"]),
        target=Target(public_url=wargame["public_url"], hosts=tuple(wargame["hosts"])),
        objectives=tuple(ObjectiveLine(key=one.key, name=one.name, state=one.state)
                         for one in referee.objectives(found)),
        origins=origin_lines(rows), hp=hp_of(found, rows))


CUSTOMERS_PROGRAM = "deploy/traffic/users.py"


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
    attacker = range_of(found).runner(ATTACKER)
    box.place_customers(attacker, (Path(configured().range.source) / CUSTOMERS_PROGRAM).read_text(encoding="utf-8"))
    return box.run_customers(attacker, json.dumps(dict(plan)))


def stop_customers(found: Round) -> None:
    box.stop_customers(range_of(found).runner(ATTACKER))


def customer_records(found: Round, offset: int, limit: int) -> str:
    return box.customer_records(range_of(found).runner(ATTACKER), offset, limit)


def lease_range(lease: Lease):
    reached = substrate(configured().range)
    if hasattr(reached, "in_slot") and lease.slot:
        return reached.in_slot(lease.slot)
    return reached


def cases_of(wargame: Mapping[str, Any]) -> list[dict[str, Any]]:
    return firing.load_cases(Path(configured().range.source) / CASES / wargame["case_file"])


def probe_request(prepared, host: str) -> dict:
    found = urlsplit(prepared.url)
    body = prepared.body.decode() if isinstance(prepared.body, bytes) else prepared.body
    headers = {name: value for name, value in prepared.headers.items()
               if name.lower() not in SET_BY_PLATFORM}
    return {"method": prepared.method, "host": host, "path": found.path + (f"?{found.query}" if found.query else ""),
            "headers": headers, **({"body": body} if body is not None else {})}


def fire_probe(lease: Lease, wargame: Mapping[str, Any], case: Mapping[str, Any], marker: str) -> Probed:
    settings, reached = configured(), lease_range(lease)
    offered = box.find(reached.describe(), None, settings.box)
    box.wear_origin(offered, reached.runner(PROXY))
    started = now()
    if tools.is_tool_case(dict(case)):
        launch = box.launch_with(reached.launcher(offered["id"]), settings.box)
        ran = firing.fire(dict(case), launch, settings.box.target_url, runs=box.SQLMAP_RUNS, marker=marker)
        return Probed(case=case["name"], marker=marker, request=None, status=0, body="", output=ran.output,
                      source_ip=offered["source_ip"], started=started, ended=now())
    attacker = reached.runner(ATTACKER)

    def launch(argv: list[str], timeout: float = firing.REQUEST_TIMEOUT):
        return attacker(argv, timeout=timeout)

    host = list(wargame["hosts"])[0]
    hosted = tools.apply_prefetch(with_host(dict(case), host), settings.box.target_url, launch,
                                  firing.REQUEST_TIMEOUT)
    prepared = firing.build_request(hosted, settings.box.target_url, marker=marker)
    request = probe_request(prepared, host)
    answer, started, ended = sent_over(attacker, prepared.method, prepared.url,
                                       {**request["headers"], "Host": host, tools.MARKER_HEADER: marker},
                                       request.get("body"))
    return Probed(case=case["name"], marker=marker, request=request, status=answer.status, body=answer.body,
                  output="", source_ip=offered["source_ip"], started=started, ended=ended)
