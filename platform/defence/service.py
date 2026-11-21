from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from content import service as content
from cr import config, errors
from defence import alerts as alert_feed
from defence import disable, drift, kibana, ruletest
from defence.models import Detection, DisabledRule, RuleSet, RuleTest
from domain.round_rules import Phase
from domain.types import ENGINE_IDS, ENGINE_WAF, ENGINES, DetectionRecord
from domain.verdicts import VerdictTable
from events import log
from ingest import elastic
from match.models import Lease, Round, Seat
from range import declaration, jump, substrate
from referee import service as referee
from rules import crs, suricata

DEFENCE = "defence"
ALERTS_PAGE = 200
GATEWAY_ROLE = "gateway"
TERMINAL = "/vm-terminal/defence/{round}/"
ANALYST_ACCOUNT = "analyst"
DISCOVER = "{base}/s/{space}/app/discover"
FORBIDDEN, BAD_GATEWAY = 403, 502


@dataclass(frozen=True)
class Head:
    version: int
    body: str | None


@dataclass(frozen=True)
class Applied:
    rule_set: RuleSet
    sensors: tuple[dict, ...]


@dataclass(frozen=True)
class GateAnswer:
    status: int
    headers: tuple[tuple[str, str], ...] = ()
    body: bytes = b""
    refused: str = ""

    @property
    def error(self) -> str:
        return "Forbidden" if self.status == FORBIDDEN else "Bad Gateway"


def configured() -> config.Config:
    return config.build(source=Path(settings.CR_SOURCE))


def lease_range(lease: Lease, cfg: config.Config):
    whole = substrate.substrate(cfg.range)
    return whole.in_slot(lease.slot) if lease.slot else whole


def slot_range(found: Round, cfg: config.Config):
    return lease_range(found.lease, cfg)


def wired(found: Round, cfg: config.Config | None = None) -> ruletest.Wired:
    return lease_wired(found.lease, cfg)


def lease_wired(lease: Lease, cfg: config.Config | None = None) -> ruletest.Wired:
    cfg = cfg or configured()
    reached = lease_range(lease, cfg)
    return ruletest.Wired(
        sensors=tuple(ruletest.Sensor(config=sensor, runner=reached.runner(sensor.role),
                                      node=reached.node_runner(sensor.role)) for sensor in cfg.sensors),
        gateway=reached.runner(cfg.waf.role), waf=cfg.waf)


def engine_given(engine: str) -> str:
    if engine not in ENGINES:
        raise errors.NotFound()
    return engine


def head_of(found: Round, engine: str) -> RuleSet | None:
    return RuleSet.objects.filter(round=found, engine=engine).order_by("-version").first()


def version_of(found: Round, engine: str) -> int:
    head = head_of(found, engine)
    return head.version if head else 0


def state(found: Round) -> dict:
    problem, wargame = found.snapshot.get("problem") or {}, found.snapshot.get("wargame") or {}
    return {
        "round": found.pk, "matchup": found.matchup, "phase": found.phase, "started": found.started,
        "ends_at": found.ends_at, "end_reason": found.end_reason,
        "brief": {"title": problem.get("title", ""), "summary": problem.get("summary", ""),
                  "body": problem.get("body", "")},
        "target": {"public_url": wargame.get("public_url", ""), "hosts": list(wargame.get("hosts") or [])},
        "objectives": [vars(objective) for objective in referee.objectives(found)],
        "ids": {"version": version_of(found, ENGINE_IDS)}, "waf": {"version": version_of(found, ENGINE_WAF)},
        "alerts_total": Detection.objects.filter(round=found).count(),
    }


def alerts(found: Round, after: int = 0, engine: str = "", rule: str = "", src: str = "") -> tuple[list, int]:
    rows = Detection.objects.filter(round=found, id__gt=after)
    if engine:
        rows = rows.filter(engine=engine)
    if rule:
        rows = rows.filter(rule=rule)
    if src:
        rows = rows.filter(src_ip=src)
    page = list(rows.order_by("id")[:ALERTS_PAGE])
    return page, page[-1].pk if page else after


def detections(found: Round) -> tuple[DetectionRecord, ...]:
    return tuple(DetectionRecord(detection_id=row.detection_id, timestamp=row.timestamp, src_ip=row.src_ip,
                                 marker=row.marker, engine=row.engine, rule=row.rule, signature=row.signature,
                                 uri=row.uri, blocked=row.blocked)
                 for row in Detection.objects.filter(round=found).order_by("timestamp", "id"))


def ingest_alerts(found: Round) -> list[Detection]:
    return alert_feed.ingest(found, configured().elastic)


def encoded(cursor: Mapping[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(dict(cursor), sort_keys=True).encode()).decode()


def decoded(token: str) -> dict:
    try:
        cursor = json.loads(base64.urlsafe_b64decode(token.encode()))
    except (binascii.Error, ValueError) as broken:
        raise errors.Invalid(code="invalid", path="after") from broken
    if not isinstance(cursor, dict):
        raise errors.Invalid(code="invalid", path="after")
    return cursor


def traffic(found: Round, after: str = "") -> dict:
    cfg = configured().elastic
    start = found.started or found.lease.opened
    cursor = decoded(after) if after else {"at": start.isoformat()}
    events, moved = elastic.access_events(cfg.url, cfg.index_of(found.lease.slot or 0), cursor)
    by_origin: dict[str, dict] = {}
    for event in events:
        if not event["source_ip"]:
            continue
        origin = by_origin.setdefault(event["source_ip"], {"ip": event["source_ip"], "requests": 0, "refused": 0,
                                                           "last_at": None})
        origin["requests"] += 1
        origin["refused"] += int(event["refused"])
        if event["at"] and (origin["last_at"] is None or event["at"] > origin["last_at"]):
            origin["last_at"] = event["at"]
    return {"by_origin": sorted(by_origin.values(), key=lambda origin: origin["ip"]), "next": encoded(moved)}


def wargame_of(found: Round):
    declared = content.read_catalog().get(found.snapshot["wargame"]["id"])
    if declared is None:
        raise errors.ServerError()
    return declared


def manifest_marker(declared, case: str) -> str | None:
    entry = (declared.probes.cases if declared.probes else {}).get(case)
    if entry is None:
        return None
    return str(entry.get("marker") or case) if isinstance(entry, Mapping) else case


def chosen_cases(found: Round, declared, cases: Sequence[str] | None) -> list[str]:
    for case in cases or ():
        if declared.case(case) is None:
            raise errors.NotFound(code="unknown_case", path="cases")
    setup = found.snapshot.get("round") or {}
    if cases:
        malicious = [case for case in dict.fromkeys(cases) if declared.case(case).malicious]
    elif setup.get("probe_cases"):
        malicious = list(setup["probe_cases"])
    else:
        malicious = [case.name for case in declared.cases if case.malicious]
    benign = list(setup.get("benign_cases") or declared.benign_cases)
    return malicious + [case for case in benign if case not in malicious]


def recordings(found: Round, cases: Sequence[str] | None = None) -> list[ruletest.Recording]:
    declared = wargame_of(found)
    folder = Path(settings.CR_SOURCE) / "wargames" / declared.id / "probes"
    made = []
    for name in chosen_cases(found, declared, cases):
        case = declared.case(name)
        marker = manifest_marker(declared, name)
        made.append(ruletest.Recording(case=name, malicious=case.malicious, tool_case=case.tool_case,
                                       expect=case.expect, marker=marker or name, in_manifest=marker is not None,
                                       folder=folder))
    return made


def probes(found: Round) -> list[dict]:
    return [{"case": one.case, "malicious": one.malicious, "recorded": one.in_manifest, "tool_case": one.tool_case}
            for one in recordings(found)]


def rules_text(found: Round, cfg: config.Config | None = None) -> Head:
    head = head_of(found, ENGINE_IDS)
    if head is not None:
        return Head(version=head.version, body=head.body)
    cfg = cfg or configured()
    if not cfg.sensors:
        raise errors.Unavailable(code="sensor_unavailable")
    sensor = cfg.sensors[0]
    return Head(version=0, body=suricata.current(slot_range(found, cfg).runner(sensor.role), sensor))


def ids_rules(found: Round) -> dict:
    head = rules_text(found)
    return {"text": head.body, "version": head.version}


def waf_posture(found: Round) -> dict:
    head = head_of(found, ENGINE_WAF)
    if head is not None:
        return {"posture": json.loads(head.body), "version": head.version}
    cfg = configured()
    read = crs.read(slot_range(found, cfg).runner(cfg.waf.role), cfg.waf)
    return {"posture": {key: value for key, value in read.items() if key != "file"}, "version": 0}


def versions(found: Round, engine: str) -> list[RuleSet]:
    return list(RuleSet.objects.filter(round=found, engine=engine_given(engine)).order_by("version"))


def check_ids(found: Round, text: str) -> dict:
    found_errors = ruletest.ids_errors(text, wired(found).sensors)
    return {"ok": not found_errors, "errors": found_errors}


def check_waf(found: Round, posture: Mapping[str, Any]) -> dict:
    found_errors = ruletest.check_waf(found, posture, wired(found))
    return {"ok": not found_errors, "errors": found_errors}


def test_rules(found: Round, seat: Seat | None, engine: str, given: Any,
               cases: Sequence[str] | None = None) -> RuleTest:
    engine_given(engine)
    chosen = recordings(found, cases)
    return ruletest.run(found, seat, engine, given, chosen, wired(found))


def rule_test(found: Round, engine: str, test_id: int) -> RuleTest:
    made = RuleTest.objects.filter(round=found, engine=engine_given(engine), pk=test_id).first()
    if made is None:
        raise errors.NotFound()
    return made


def latest_test(found: Round, engine: str, seat: Seat | None = None) -> RuleTest | None:
    tests = RuleTest.objects.filter(round=found, engine=engine_given(engine))
    if seat is not None:
        tests = tests.filter(seat=seat)
    return tests.order_by("-id").first()


def latest_table(found: Round, engine: str, seat: Seat | None = None) -> VerdictTable | None:
    made = latest_test(found, engine, seat)
    return None if made is None else ruletest.table_of(made.result)


def start_tuning(found: Round) -> dict:
    posture = (found.snapshot.get("round") or {}).get("posture") or found.snapshot.get("start_posture") or {}
    return dict(posture.get("crs_tuning") or {})


def tuning_at(found: Round, at: datetime | None = None) -> dict:
    sets = RuleSet.objects.filter(round=found, engine=ENGINE_WAF)
    if at is not None:
        sets = sets.filter(applied_at__lte=at)
    head = sets.order_by("-version").first()
    return json.loads(head.body) if head else start_tuning(found)


def tested_of(found: Round, engine: str, seat: Seat | None, tested: int | None) -> RuleTest | None:
    if tested is None:
        return None
    made = RuleTest.objects.filter(round=found, engine=engine, pk=tested, seat=seat).first()
    if made is None:
        raise errors.Invalid(code="does_not_exist", path="tested")
    return made


def refused_while_writing(sensors: Sequence[dict], refused: errors.DomainError) -> errors.EngineRefused:
    return errors.EngineRefused(code="apply_refused", params={"sensors": list(sensors), "message": str(refused)})


def rolled_back(previous: str, written: Sequence[ruletest.Sensor]) -> list[dict]:
    shown = []
    for sensor in written:
        try:
            suricata.seed(previous, sensor.runner, sensor.config)
            shown.append({"name": sensor.config.name, "ok": False, "rolled_back": True})
        except errors.DomainError:
            shown.append({"name": sensor.config.name, "ok": False, "rolled_back": False})
    return shown


def written_to_sensors(text: str, previous: str, sensors: Sequence[ruletest.Sensor]) -> tuple[dict, ...]:
    written: list[ruletest.Sensor] = []
    for at, sensor in enumerate(sensors):
        try:
            suricata.apply(text, sensor.runner, sensor.config)
        except errors.DomainError as refused:
            if not written and isinstance(refused, suricata.RuleSyntax):
                raise
            shown = rolled_back(previous, written) + [{"name": sensor.config.name, "ok": False}]
            shown += [{"name": rest.config.name, "ok": False} for rest in sensors[at + 1:]]
            if isinstance(refused, errors.EngineRefused):
                raise refused_while_writing(shown, refused) from refused
            raise
        written.append(sensor)
    return tuple({"name": sensor.config.name, "ok": True} for sensor in sensors)


def locked_head(found: Round, engine: str, base_version: int) -> RuleSet | None:
    head = RuleSet.objects.select_for_update().filter(round=found, engine=engine).order_by("-version").first()
    current = head.version if head else 0
    if base_version != current:
        raise errors.Conflict(code="stale_version", params={"current_version": current})
    return head


def recorded(found: Round, engine: str, head: RuleSet | None, body: str, sensors: Sequence[dict],
             tested: RuleTest | None, seat: Seat | None) -> RuleSet:
    made = RuleSet.objects.create(round=found, engine=engine, version=(head.version if head else 0) + 1, body=body,
                                  applied_at=timezone.now(), tested=tested, seat=seat,
                                  same_as_tested=tested is not None and tested.body_sha == ruletest.sha(body),
                                  sensors=list(sensors))
    log.append(found.pk, "rule.applied", {"engine": engine, "version": made.version}, seat_side=DEFENCE)
    return made


def apply_ids(found: Round, text: str, base_version: int, seat: Seat | None = None,
              tested: int | None = None) -> Applied:
    unread = ruletest.unread_errors(text)
    if unread:
        raise errors.EngineRefused(code="unread_sid", errors=tuple(
            errors.FieldError(path=error["path"], code=error["code"], line=error["line"],
                              params={"message": error["message"]}) for error in unread))
    test = tested_of(found, ENGINE_IDS, seat, tested)
    reached = wired(found)
    if not reached.sensors:
        raise errors.Unavailable(code="sensor_unavailable")
    with transaction.atomic():
        head = locked_head(found, ENGINE_IDS, base_version)
        previous = head.body if head else suricata.current(reached.sensors[0].runner, reached.sensors[0].config)
        sensors = written_to_sensors(text, previous, reached.sensors)
        return Applied(rule_set=recorded(found, ENGINE_IDS, head, text, sensors, test, seat), sensors=sensors)


def apply_waf(found: Round, posture: Mapping[str, Any], base_version: int, seat: Seat | None = None,
              tested: int | None = None) -> Applied:
    tuning = ruletest.checked_posture(posture)
    test = tested_of(found, ENGINE_WAF, seat, tested)
    reached = wired(found)
    with transaction.atomic():
        head = locked_head(found, ENGINE_WAF, base_version)
        try:
            crs.apply(tuning, reached.gateway, reached.waf)
        except crs.TuningRefused as refused:
            raise ruletest.posture_refusal(refused) from refused
        return Applied(rule_set=recorded(found, ENGINE_WAF, head, ruletest.canonical(tuning), (), test, seat), sensors=())


def apply_posture(found: Round) -> None:
    posture = (found.snapshot.get("round") or {}).get("posture") or found.snapshot.get("start_posture")
    if not posture:
        return
    if posture.get("suricata_rules"):
        apply_ids(found, posture["suricata_rules"], version_of(found, ENGINE_IDS))
    apply_waf(found, posture["crs_tuning"], version_of(found, ENGINE_WAF))


def disabled(found: Round) -> list[DisabledRule]:
    return list(DisabledRule.objects.filter(round=found, enabled_at__isnull=True).order_by("id"))


def disable_rule(found: Round, sid: int, minutes: float, reason: str = "",
                 now: datetime | None = None) -> DisabledRule:
    now = now or timezone.now()
    head = rules_text(found)
    original = disable.find(head.body, sid)
    if original is None:
        raise errors.NotFound(path="sid")
    expires_at = now + timedelta(minutes=minutes)
    apply_ids(found, disable.comment_out(head.body, sid, expires_at.isoformat()), head.version)
    made = DisabledRule.objects.create(round=found, sid=sid, original=original, reason=reason,
                                       expires_at=expires_at)
    log.append(found.pk, "rule.disabled", {"sid": sid, "expires_at": expires_at.isoformat()}, seat_side=DEFENCE)
    return made


def enabled_text(text: str, record: DisabledRule) -> str | None:
    put_back = disable.discard if disable.find(text, record.sid) is not None else disable.uncomment
    try:
        return put_back(text, record.sid, record.original)
    except KeyError:
        return None


def enable(found: Round, record: DisabledRule, now: datetime | None = None) -> None:
    head = rules_text(found)
    restored = enabled_text(head.body, record)
    if restored is not None:
        apply_ids(found, restored, head.version)
    record.enabled_at = now or timezone.now()
    record.save(update_fields=["enabled_at"])


def enable_rule(found: Round, sid: int) -> None:
    record = DisabledRule.objects.filter(round=found, sid=sid, enabled_at__isnull=True).order_by("-id").first()
    if record is None:
        raise errors.NotFound(path="sid")
    enable(found, record)


def enable_expired(found: Round, now: datetime | None = None) -> list[int]:
    now = now or timezone.now()
    due = list(DisabledRule.objects.filter(round=found, enabled_at__isnull=True, expires_at__lte=now))
    for record in due:
        enable(found, record, now)
    return [record.sid for record in due]


def check_drift(found: Round, now: datetime | None = None) -> bool:
    cfg = configured()
    return drift.check(found.pk, slot_range(found, cfg).runner(cfg.waf.role), cfg.waf, now or timezone.now())


def posture_drift(found: Round) -> bool:
    return drift.any_drift(found.pk)


def terminal(found: Round, seat: Seat) -> dict:
    if found.phase in (Phase.CREATED.value, Phase.STARTING.value):
        raise errors.Conflict(code="round_not_started")
    if found.phase == Phase.ENDED.value:
        raise errors.Conflict(code="round_closed")
    cfg = configured()
    reached = slot_range(found, cfg)
    access = jump.open_access(seat.pk, reached.address(cfg.waf.role), reached.runner(cfg.waf.role),
                              ANALYST_ACCOUNT, cfg.jump)
    return {"ws_url": TERMINAL.format(round=found.pk),
            "ssh": {**asdict(access), "expires_at": found.ends_at or found.lease.expires_at}}


def terminal_shell(seat: Seat) -> tuple[str, str]:
    grant = jump.granted(seat.pk, configured().jump)
    if grant is None:
        raise errors.NotSeated()
    return grant.address, ANALYST_ACCOUNT


def revoke_terminal(found: Round) -> int:
    cfg = configured()

    def waf():
        return slot_range(found, cfg).runner(cfg.waf.role)

    revoked = sum(1 for seat in Seat.objects.filter(round=found, side=DEFENCE)
                  if jump.close_access(seat.pk, waf, ANALYST_ACCOUNT, cfg.jump) is not None)
    if revoked:
        jump.end_account(waf(), ANALYST_ACCOUNT)
    return revoked


def close(found: Round) -> None:
    revoke_terminal(found)


def index_of(found: Round, cfg: config.Config) -> str:
    return cfg.elastic.index_of(found.lease.slot or 0)


def gateway_name(cfg: config.Config) -> str:
    return declaration.read(Path(cfg.range.declaration), Path(cfg.range.source)).roles.get(GATEWAY_ROLE, "")


def prepare_kibana(found: Round, again: bool = True) -> bool:
    cfg = configured()
    return kibana.session_view_ready(index_of(found, cfg), gateway_name(cfg), cfg.kibana, again=again)


def kibana_space(found: Round) -> dict:
    cfg = configured()
    if not prepare_kibana(found, again=False):
        raise errors.Unavailable(code="kibana_unavailable")
    space = kibana.session_view_id(index_of(found, cfg))
    return {"space_url": DISCOVER.format(base=kibana.BASE_PATH, space=space)}


def kibana_spaces(user) -> dict[str, str] | None:
    if getattr(user, "is_staff", False):
        return None
    if getattr(user, "pk", None) is None:
        return {}
    cfg = configured()
    held = (Seat.objects.filter(user_id=user.pk, side=DEFENCE).exclude(round__phase=Phase.ENDED.value)
            .select_related("round__lease"))
    return {kibana.session_view_id(index): index for seat in held if (index := index_of(seat.round, cfg))}


def kibana_gate(user, method: str, uri: str, headers: Mapping[str, str], body: bytes) -> GateAnswer:
    spaces, asked = kibana_spaces(user), kibana.space_of(uri)
    if spaces is not None and asked is not None and asked not in spaces:
        return GateAnswer(status=FORBIDDEN, refused="kibana.refused.space")
    if kibana.refusal(method, uri, body, spaces):
        return GateAnswer(status=FORBIDDEN, refused="kibana.refused.call")
    try:
        status, kept, answered = kibana.forward(method, uri, headers, body, configured().kibana)
    except (OSError, ValueError):
        return GateAnswer(status=BAD_GATEWAY, refused="kibana.unanswered")
    return GateAnswer(status=status, headers=tuple(kept), body=answered)


PROBE_CAPTURES = "/tmp/cr-probes"


def detection_only(lease: Lease) -> dict:
    reached = lease_wired(lease)
    standing = crs.read(reached.gateway, reached.waf)
    tuning = ruletest.checked_posture({**{key: value for key, value in standing.items() if key != "file"},
                                       "paranoia": standing.get("paranoia") or 1, "detection_only": True})
    try:
        crs.apply(tuning, reached.gateway, reached.waf)
    except crs.TuningRefused as refused:
        raise ruletest.posture_refusal(refused) from refused
    return tuning


def start_capture(lease: Lease, name: str, seconds: int) -> suricata.Capture:
    reached = lease_wired(lease)
    if not reached.sensors:
        raise errors.Unavailable(code="sensor_unavailable")
    sensor = reached.sensors[0]
    return suricata.capture(sensor.node, sensor.config, f"{PROBE_CAPTURES}/{name}.pcap", seconds)


def finish_capture(lease: Lease, held: suricata.Capture) -> bytes:
    sensor = lease_wired(lease).sensors[0]
    suricata.stop_capture(sensor.node, held)
    return suricata.captured(sensor.node, held)
