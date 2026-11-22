from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from cr import config, errors
from cr.config import configured
from domain.types import ENGINE_IDS, ENGINE_WAF, ENGINES, RESPONSE_VERSION, ResponseRecord
from sandbox import crs, reach, suricata
from scoring import losses as referee
from telemetry import events as log
from telemetry.models import Detection
from training.content import problems as content
from training.defence import ruletest, terminal
from training.models import Allocation, Round, RuleSet, RuleTest, Player

DEFENCE = "defence"
IDS_FILE = ruletest.IDS_FILE
SETUP, CONSOLE, TERMINAL = "setup", "console", "terminal"


@dataclass(frozen=True)
class Applied:
    rule_set: RuleSet
    sensors: tuple[dict, ...]


def wired(found: Round, cfg: config.Config | None = None) -> ruletest.Wired:
    return allocation_wired(found.allocation, cfg)


def allocation_wired(allocation: Allocation, cfg: config.Config | None = None) -> ruletest.Wired:
    cfg = cfg or configured()
    reached = reach.allocation_range(allocation, cfg)
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


def first_sensor(found: Round, cfg: config.Config | None = None):
    cfg = cfg or configured()
    if not cfg.sensors:
        raise errors.Unavailable(code="sensor_unavailable")
    sensor = cfg.sensors[0]
    return reach.range_of(found, cfg).runner(sensor.role), sensor


def sensor_node(found: Round, cfg: config.Config | None = None):
    cfg = cfg or configured()
    if not cfg.sensors:
        raise errors.Unavailable(code="sensor_unavailable")
    sensor = cfg.sensors[0]
    return reach.range_of(found, cfg).node_runner(sensor.role), sensor


def ids_reload_at(found: Round) -> float | None:
    snapshot = suricata.reloaded(*sensor_node(found))
    return snapshot.at if snapshot else None


def waf_reload_at(gateway, waf) -> float | None:
    snapshot = crs.reloaded(gateway, waf)
    return snapshot.at if snapshot else None


def ids_rules(found: Round) -> dict:
    runner, sensor = first_sensor(found)
    live = suricata.current(runner, sensor)
    head = head_of(found, ENGINE_IDS)
    return {"text": live, "version": head.version if head else 0,
            "recorded": head is not None and head.sha == ruletest.files_sha({IDS_FILE: live})}


def gateway_of(found: Round, cfg: config.Config | None = None):
    cfg = cfg or configured()
    return reach.range_of(found, cfg).runner(cfg.waf.role), cfg.waf


def waf_files(found: Round) -> dict:
    gateway, waf = gateway_of(found)
    live = crs.read(gateway, waf)
    head = head_of(found, ENGINE_WAF)
    sha = ruletest.files_sha(live)
    return {"files": [{"path": path, "text": text} for path, text in live.items()], "sha": sha,
            "version": head.version if head else 0, "recorded": head is not None and head.sha == sha}


def versions(found: Round, engine: str) -> list[RuleSet]:
    return list(RuleSet.objects.filter(round=found, engine=engine_given(engine)).order_by("version"))


def applied(found: Round) -> list[ResponseRecord]:
    return [ResponseRecord(at=rule_set.took_effect, kind=RESPONSE_VERSION)
            for rule_set in RuleSet.objects.filter(round=found).exclude(source=SETUP)]


def version(found: Round, engine: str, number: int) -> RuleSet:
    made = RuleSet.objects.filter(round=found, engine=engine_given(engine), version=number).first()
    if made is None:
        raise errors.NotFound()
    return made


def check_waf(found: Round, files: Mapping[str, str]) -> dict:
    found_errors = ruletest.check_waf(found, files, wired(found))
    return {"ok": not found_errors, "errors": found_errors}


def test_rules(found: Round, player: Player | None, engine: str, given: Any,
               cases: Sequence[str] | None = None) -> RuleTest:
    engine_given(engine)
    chosen = recordings(found, cases)
    return ruletest.run(found, player, engine, given, chosen, wired(found))


def rule_test(found: Round, engine: str, test_id: int) -> RuleTest:
    made = RuleTest.objects.filter(round=found, engine=engine_given(engine), pk=test_id).first()
    if made is None:
        raise errors.NotFound()
    return made


def tested_of(found: Round, engine: str, player: Player | None, tested: int | None) -> RuleTest | None:
    if tested is None:
        return None
    made = RuleTest.objects.filter(round=found, engine=engine, pk=tested, player=player).first()
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


def recorded(found: Round, engine: str, head: RuleSet | None, files: Mapping[str, str], sensors: Sequence[dict],
             tested: RuleTest | None, source: str = CONSOLE, reloaded: float | None = None) -> RuleSet:
    sha = ruletest.files_sha(files)
    made = RuleSet.objects.create(round=found, engine=engine, version=(head.version if head else 0) + 1,
                                  files=dict(files), sha=sha, source=source, applied_at=timezone.now(),
                                  tested=tested,
                                  same_as_tested=tested is not None and tested.sha == sha, sensors=list(sensors),
                                  reloaded=reloaded)
    log.append(found.pk, "rule.applied", {"engine": engine, "version": made.version, "source": source},
               player_side=DEFENCE)
    return made


def apply_ids(found: Round, text: str, base_version: int, source: str = SETUP) -> Applied:
    reached = wired(found)
    if not reached.sensors:
        raise errors.Unavailable(code="sensor_unavailable")
    with transaction.atomic():
        head = locked_head(found, ENGINE_IDS, base_version)
        previous = (head.files.get(IDS_FILE, "") if head
                    else suricata.current(reached.sensors[0].runner, reached.sensors[0].config))
        sensors = written_to_sensors(text, previous, reached.sensors)
        made = recorded(found, ENGINE_IDS, head, {IDS_FILE: text}, sensors, None, source, ids_reload_at(found))
        return Applied(rule_set=made, sensors=sensors)


def apply_waf(found: Round, files: Mapping[str, str], base_version: int, player: Player | None = None,
              tested: int | None = None, source: str = CONSOLE) -> Applied:
    reached = wired(found)
    ruletest.checked_files(files, reached.waf)
    test = tested_of(found, ENGINE_WAF, player, tested)
    with transaction.atomic():
        head = locked_head(found, ENGINE_WAF, base_version)
        try:
            merged = crs.apply(files, reached.gateway, reached.waf)
        except crs.WafRefused as refused:
            raise ruletest.waf_refusal(refused) from refused
        return Applied(rule_set=recorded(found, ENGINE_WAF, head, merged, (), test, source,
                                         waf_reload_at(reached.gateway, reached.waf)), sensors=())


def record_live_waf(found: Round, source: str, live: Mapping[str, str] | None = None,
                    reloaded: float | None = None) -> RuleSet | None:
    gateway, waf = gateway_of(found)
    if live is None:
        live = crs.read(gateway, waf)
        reloaded = waf_reload_at(gateway, waf)
    with transaction.atomic():
        head = RuleSet.objects.select_for_update().filter(round=found, engine=ENGINE_WAF).order_by("-version").first()
        if head is not None and head.sha == ruletest.files_sha(live):
            consumed(head, reloaded)
            return None
        return recorded(found, ENGINE_WAF, head, live, (), None, source, reloaded)


def consumed(rule_set: RuleSet, reloaded: float | None) -> None:
    if reloaded is not None and rule_set.reloaded != reloaded:
        rule_set.reloaded = reloaded
        rule_set.save(update_fields=["reloaded"])


def record_live_ids(found: Round, source: str, live: str | None = None,
                    reloaded: float | None = None) -> RuleSet | None:
    runner, sensor = first_sensor(found)
    if live is None:
        live = suricata.current(runner, sensor)
        reloaded = ids_reload_at(found)
    files = {IDS_FILE: live}
    with transaction.atomic():
        head = RuleSet.objects.select_for_update().filter(round=found, engine=ENGINE_IDS).order_by("-version").first()
        if head is not None and head.sha == ruletest.files_sha(files):
            consumed(head, reloaded)
            return None
        return recorded(found, ENGINE_IDS, head, files, ({"name": sensor.name, "ok": True},), None, source, reloaded)


def apply_posture(found: Round) -> None:
    posture = (found.snapshot.get("round") or {}).get("posture") or found.snapshot.get("start_posture") or {}
    if posture.get("suricata_rules"):
        apply_ids(found, posture["suricata_rules"], version_of(found, ENGINE_IDS), source=SETUP)
    else:
        record_live_ids(found, SETUP)
    if posture.get("waf_files"):
        apply_waf(found, posture["waf_files"], version_of(found, ENGINE_WAF), source=SETUP)
    else:
        record_live_waf(found, SETUP)


def record_terminal_reload(found: Round) -> bool:
    waf = record_waf_terminal_reload(found)
    ids = record_ids_terminal_reload(found)
    return waf or ids


def record_ids_terminal_reload(found: Round) -> bool:
    head = head_of(found, ENGINE_IDS)
    if head is None:
        return False
    try:
        snapshot = suricata.reloaded(*sensor_node(found))
        if snapshot is None or snapshot.at == head.reloaded:
            return False
        measured = suricata.refusals(snapshot.text)
        if measured:
            runner, sensor = first_sensor(found)
            suricata.seed(head.files.get(IDS_FILE, ""), runner, sensor)
            put_back(found, head, ENGINE_IDS, [one.message for one in measured], snapshot.at)
            return False
    except (errors.Unavailable, suricata.RuleApplyError):
        return False
    return record_live_ids(found, TERMINAL, snapshot.text, snapshot.at) is not None


def record_waf_terminal_reload(found: Round) -> bool:
    head = head_of(found, ENGINE_WAF)
    if head is None:
        return False
    gateway, waf = gateway_of(found)
    try:
        snapshot = crs.reloaded(gateway, waf)
        if snapshot is None or snapshot.at == head.reloaded:
            return False
        measured = crs.refusals(snapshot.files, waf)
        if measured:
            crs.apply(head.files, gateway, waf)
            put_back(found, head, ENGINE_WAF, [one["message"] for one in measured], snapshot.at)
            return False
    except (crs.WafUnreadable, crs.WafRefused):
        return False
    return record_live_waf(found, TERMINAL, snapshot.files, snapshot.at) is not None


def put_back(found: Round, head: RuleSet, engine: str, messages: Sequence[str], reloaded: float) -> None:
    consumed(head, reloaded)
    log.append(found.pk, "rule.refused", {"engine": engine, "version": head.version, "message": "; ".join(messages)},
               player_side=DEFENCE)


def close(found: Round) -> None:
    terminal.revoke_terminal(found)


PROBE_CAPTURES = "/tmp/cr-probes"


def detection_only(allocation: Allocation) -> dict[str, str]:
    reached = allocation_wired(allocation)
    files = crs.detection_only(crs.read(reached.gateway, reached.waf), reached.waf)
    try:
        return crs.apply(files, reached.gateway, reached.waf)
    except crs.WafRefused as refused:
        raise ruletest.waf_refusal(refused) from refused


def start_capture(allocation: Allocation, name: str, seconds: int) -> suricata.Capture:
    reached = allocation_wired(allocation)
    if not reached.sensors:
        raise errors.Unavailable(code="sensor_unavailable")
    sensor = reached.sensors[0]
    return suricata.capture(sensor.node, sensor.config, f"{PROBE_CAPTURES}/{name}.pcap", seconds)


def finish_capture(allocation: Allocation, held: suricata.Capture) -> bytes:
    sensor = allocation_wired(allocation).sensors[0]
    suricata.stop_capture(sensor.node, held)
    return suricata.captured(sensor.node, held)
