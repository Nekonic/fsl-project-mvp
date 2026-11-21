from __future__ import annotations

import base64
import hashlib
import json
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cr import errors
from cr.config import SensorConfig, WafConfig
from domain import verdicts
from domain.types import ENGINE_IDS, ENGINE_WAF, FN, FP, TN, TP, DetectionRecord
from sandbox import crs, suricata
from sandbox.runner import Runner
from telemetry import events as log
from training.models import RuleSet, RuleTest

CHECK_SCRATCH_ID = 999999
REFUSED_STATUSES = (400, 403)
DEFENCE = "defence"
IDS_FILE = "local.rules"

_LOCKS: dict[tuple[int, str], threading.Lock] = {}
_GUARD = threading.Lock()


@dataclass(frozen=True)
class Sensor:
    config: SensorConfig
    runner: Runner
    node: Runner


@dataclass(frozen=True)
class Wired:
    sensors: tuple[Sensor, ...]
    gateway: Runner
    waf: WafConfig


@dataclass(frozen=True)
class Recording:
    case: str
    malicious: bool
    tool_case: bool
    expect: str | None
    marker: str
    in_manifest: bool
    folder: Path

    @property
    def pcap(self) -> Path:
        return self.folder / f"{self.case}.pcap"

    @property
    def request(self) -> Path:
        return self.folder / f"{self.case}.request.json"

    @property
    def response(self) -> Path:
        return self.folder / f"{self.case}.response.json"

    def recorded_for(self, engine: str) -> bool:
        if engine == ENGINE_WAF and self.tool_case:
            return self.in_manifest
        needed = self.pcap if engine == ENGINE_IDS else self.request
        return self.in_manifest and needed.is_file()

    def probe(self, engine: str) -> verdicts.Probe:
        return verdicts.Probe(case=self.case, malicious=self.malicious, marker=self.marker, expect=self.expect,
                              recorded=self.recorded_for(engine), tool_case=self.tool_case)


def sha(body: str) -> str:
    return hashlib.sha256(body.encode()).hexdigest()


def files_sha(files: Mapping[str, str]) -> str:
    return sha(json.dumps(dict(files), sort_keys=True, separators=(",", ":"), ensure_ascii=False))


@contextmanager
def busy(allocation_id: int, engine: str) -> Iterator[None]:
    with _GUARD:
        lock = _LOCKS.setdefault((allocation_id, engine), threading.Lock())
    if not lock.acquire(blocking=False):
        raise errors.Conflict(code="test_busy")
    try:
        yield
    finally:
        lock.release()


def ids_errors(text: str, sensors: Sequence[Sensor]) -> list[dict]:
    found: list[dict] = []
    for sensor in sensors:
        for error in suricata.checked(text, sensor.runner, sensor.config):
            shown = {"path": "text", "code": suricata.RuleSyntax.code, "line": error.line, "message": error.message}
            if shown not in found:
                found.append(shown)
    return found


def waf_problems(found: Sequence[dict]) -> list[dict]:
    return [{"path": one["file"] or "files", "code": crs.WafRefused.code, "line": one["line"],
             "message": one["message"]} for one in found]


def refused_files(refused: crs.WafRefused) -> list[dict]:
    return [{"path": error.path or "files", "code": crs.WafRefused.code, "line": error.line,
             "message": error.params.get("message", str(refused))} for error in refused.errors]


def waf_refusal(refused: crs.WafRefused) -> errors.EngineRefused:
    return errors.EngineRefused(code=crs.WafRefused.code, errors=tuple(
        errors.FieldError(path=error["path"], code=error["code"], line=error["line"],
                          params={"message": error["message"]}) for error in refused_files(refused)))


def checked_files(files: Mapping[str, str], waf: WafConfig) -> dict[str, str]:
    try:
        return crs.checked(files, waf)
    except crs.WafRefused as refused:
        raise waf_refusal(refused) from refused


def waf_errors(files: Mapping[str, str], wired: Wired, scratch_id: int) -> list[dict]:
    try:
        return waf_problems(crs.scratch_check(dict(files), wired.gateway, wired.waf, scratch_id))
    except crs.WafRefused as refused:
        return refused_files(refused)


def files_of(engine: str, given: Any, wired: Wired) -> dict[str, str]:
    if engine == ENGINE_IDS:
        return {IDS_FILE: given}
    if not isinstance(given, Mapping):
        return {}
    return crs.read(wired.gateway, wired.waf) | {path: text for path, text in given.items() if path in wired.waf.files}


def staged_pcaps(node: Runner, folder: str, recordings: Sequence[Recording]) -> dict[str, str]:
    staged = {}
    for recording in recordings:
        path = f"{folder}/{recording.case}.pcap"
        ran = node(["sh", "-c", f"mkdir -p {folder} && base64 -d > {path}"],
                   stdin=base64.b64encode(recording.pcap.read_bytes()).decode())
        if not ran.ok:
            raise errors.Unavailable(code="sensor_unavailable")
        staged[recording.case] = path
    return staged


def ids_alerts(text: str, sensor: Sensor, recordings: Sequence[Recording], test_id: int) -> list[DetectionRecord]:
    if not recordings:
        return []
    folder = f"{sensor.config.scratch}/test-{test_id}-pcaps"
    try:
        found = suricata.offline_test(text, sensor.node, sensor.config,
                                      staged_pcaps(sensor.node, folder, recordings), f"test-{test_id}")
    finally:
        sensor.node(["rm", "-rf", folder])
    marker = {recording.case: recording.marker for recording in recordings}
    return [DetectionRecord(detection_id=f"{case}:{at}", timestamp=verdicts.RECORDING_TIME, src_ip=None,
                            marker=marker[case], engine=ENGINE_IDS, rule=alert["rule"], signature=alert["signature"])
            for case, alerts in found.items() for at, alert in enumerate(alerts)]


def probe_request(recording: Recording) -> dict:
    asked = json.loads(recording.request.read_text(encoding="utf-8"))
    request = {key: asked[key] for key in ("method", "host", "path", "headers", "body") if key in asked}
    answered = (json.loads(recording.response.read_text(encoding="utf-8"))
                if recording.response.is_file() else None)
    return {"marker": recording.marker, **request, "response": answered}


def waf_alerts(files: Mapping[str, str], wired: Wired, recordings: Sequence[Recording],
               test_id: int) -> list[DetectionRecord]:
    if not recordings:
        return []
    found = crs.scratch_test(dict(files), wired.gateway, wired.waf, test_id,
                             [probe_request(recording) for recording in recordings])
    return [DetectionRecord(detection_id=f"{marker}:{at}", timestamp=verdicts.RECORDING_TIME, src_ip=None,
                            marker=marker, engine=ENGINE_WAF, rule=alert["rule"], signature=alert["signature"],
                            blocked=answer["status"] in REFUSED_STATUSES)
            for marker, answer in found.items() for at, alert in enumerate(answer["alerts"])]


def shown(table: verdicts.VerdictTable) -> dict:
    return {
        "cases": [{"case": row.case, "malicious": row.malicious, "verdict": row.verdict,
                   "corroborated": row.corroborated,
                   "alerts": [{"rule": rule, "signature": signature} for rule, signature in row.alerts],
                   "recorded_run": row.recorded_run} for row in table.cases],
        "totals": dict(table.totals),
        "untested": [{"case": row.case, "reason": row.reason} for row in table.untested],
        "against_applied": [{"case": row.case, "was": row.was, "now": row.now} for row in table.against_applied],
    }


def table_of(result: Mapping[str, Any]) -> verdicts.VerdictTable:
    return verdicts.VerdictTable(
        cases=tuple(verdicts.CaseVerdict(case=row["case"], malicious=row["malicious"], verdict=row["verdict"],
                                         corroborated=row["corroborated"],
                                         alerts=tuple((alert["rule"], alert["signature"]) for alert in row["alerts"]),
                                         recorded_run=row["recorded_run"]) for row in result.get("cases", ())),
        totals=tuple(result.get("totals", {}).items()),
        untested=(),
        against_applied=(),
    )


def failed(found: Sequence[dict]) -> dict:
    return {"ok": False, "errors": list(found), "cases": [], "totals": {TP: 0, FN: 0, FP: 0, TN: 0},
            "untested": [], "against_applied": []}


def applied_table(round_id: int, engine: str) -> verdicts.VerdictTable | None:
    head = RuleSet.objects.filter(round_id=round_id, engine=engine).select_related("tested").order_by("-version").first()
    if head is None or head.tested is None or not head.same_as_tested or not head.tested.syntax_ok:
        return None
    return table_of(head.tested.result)


def judged(engine: str, given: Any, wired: Wired, recordings: Sequence[Recording], test_id: int,
           round_id: int) -> dict:
    tested = [recording for recording in recordings
              if verdicts.untested_reason(recording.probe(engine), engine) is None]
    if engine == ENGINE_IDS:
        alerts = ids_alerts(given, wired.sensors[0], tested, test_id)
    else:
        alerts = waf_alerts(given, wired, tested, test_id)
    table = verdicts.table([recording.probe(engine) for recording in recordings], alerts, engine,
                           applied_table(round_id, engine))
    return {"ok": True, "errors": [], **shown(table)}


def syntax_errors(engine: str, given: Any, wired: Wired, test_id: int) -> list[dict]:
    if engine == ENGINE_IDS:
        return ids_errors(given, wired.sensors)
    return waf_errors(given, wired, test_id)


def outcome(engine: str, given: Any, wired: Wired, recordings: Sequence[Recording], test_id: int,
            round_id: int) -> dict:
    found_errors = syntax_errors(engine, given, wired, test_id)
    if found_errors:
        return failed(found_errors)
    try:
        return judged(engine, given, wired, recordings, test_id, round_id)
    except crs.WafRefused as refused:
        return failed(refused_files(refused))


def run(found, player, engine: str, given: Any, recordings: Sequence[Recording], wired: Wired) -> RuleTest:
    if engine == ENGINE_IDS and not wired.sensors:
        raise errors.Unavailable(code="sensor_unavailable")
    with busy(found.allocation_id, engine):
        files = files_of(engine, given, wired)
        made = RuleTest.objects.create(round=found, player=player, engine=engine, sha=files_sha(files), files=files)
        try:
            result = outcome(engine, given if engine == ENGINE_IDS else files, wired, recordings, made.pk, found.pk)
        except BaseException:
            made.delete()
            raise
        made.syntax_ok, made.result = result["ok"], result
        made.save(update_fields=["syntax_ok", "result"])
        log.append(found.pk, "rule.tested", {"test": made.pk, "engine": engine, "ok": result["ok"]},
                   player_side=DEFENCE)
    return made


def check_waf(found, files: Mapping[str, str], wired: Wired) -> list[dict]:
    with busy(found.allocation_id, ENGINE_WAF):
        return waf_errors(files, wired, CHECK_SCRATCH_ID)
