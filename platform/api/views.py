import functools
import hashlib
import ipaddress
import json
import math
import re
import shlex
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, unquote, urlsplit

from django.conf import settings
from django.core.exceptions import BadRequest
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Max, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

import attacker
import game
import gns3
import kibana
import lesson
import scoreboard
import suppress
import topology
import wargames
import traffic
from api import customers, effect, loot, reset, scenario_run, site
from api.refusals import Conflict
from console import strings
from api.models import (
    Case,
    Detection,
    Objective,
    RuleSet,
    Session,
    Suppression,
)
from ingest import elastic
from redteam import harness, tools
import operator_log
from range import slot, substrate
from range.ports import Drifted, RangeUnavailable, Shape
from rules import crs, suricata
from scoring.correlate import correlate
from scoring.metrics import score as compute_score
from scoring.types import CORRELATION_STRATEGIES

SESSION_FIELDS = ("id", "scenario", "started_at", "ended_at", "guidance", "mode", "defense")
CASE_FIELDS = (
    "id", "case_id", "name", "malicious", "stage", "technique", "pattern",
    "expect", "correlation", "source_ip", "started_at", "ended_at", "meta",
)
DETECTION_FIELDS = (
    "id", "detection_id", "source", "signature", "severity", "timestamp",
    "src_ip", "marker",
)
DETECTION_DETAIL_FIELDS = DETECTION_FIELDS + ("raw",)
OBJECTIVE_FIELDS = ("id", "key", "name", "category", "difficulty", "achieved_at")
RULESET_FIELDS = ("id", "content", "created_at", "applied_at")
SCORE_FIELDS = ("tp", "fp", "fn", "tn", "precision", "recall", "f1", "false_positive_rate")
SUPPRESSION_FIELDS = (
    "id", "session_id", "sid", "reason", "created_at", "expires_at", "restored_at",
)

SITE_BROWSER_MARKER = site.MARKER
RESERVED_MARKERS = (SITE_BROWSER_MARKER,)
HINT_LEVELS = ("hint", "do")
LESSON_STEP_STATES = ("reached", "skipped")
MODES = ("guided", "self")
RECENT_ALERTS = 600
SHOWN_CHECK = {"choice": ("options",), "alert": ("path",), "served": ("path",), "replay": ("case",),
               "detect": ("case", "expect"), "sent": ("match",), "kali": ("case",)}
COUNT_TOLERANCE = 0.1
SERVER_ONLY = ("solved_at",)
SCHEDULE = ("attacks", "completion")
SERVER_ONLY_STEP = ("rule",)
REPLAY_MARKS = ("seed", "verify", "check", "replay")
CHECK_TIMEOUT = 10.0
SEGMENTS_KEPT_FOR = 30.0
FOLLOW_SLACK = timedelta(seconds=5)
STACK_OUTLIVES_ITS_SESSION = timedelta(minutes=3)
_segments_kept: dict = {}
SUPPRESSION_MINUTES = 60
DEFAULT_RULES = "local.rules"
RULE_ERROR = re.compile(r"\b(Error|ERRCODE)\b|<Error>")
RULE_CHANGES = threading.RLock()
SLOT_CHOICE = threading.Lock()
_TURNS_GUARD = threading.Lock()
_SLOT_TURNS: dict[int, threading.RLock] = {}
SETTLING_PHASES = ("RESETTING", "REBUILDING", "CHECKING")

def _turn(slot):
    if slot is None:
        return RULE_CHANGES
    with _TURNS_GUARD:
        return _SLOT_TURNS.setdefault(slot, threading.RLock())

def _slotted(adapter) -> bool:
    return hasattr(adapter, "in_slot")

def _slot_of(session) -> int:
    return session.slot if session is not None and session.slot else 1

def _in_slot(adapter, number: int):
    return adapter.in_slot(number) if _slotted(adapter) else adapter

def _turn_of(session, adapter=None):
    adapter = adapter or substrate()
    if not _slotted(adapter):
        return RULE_CHANGES
    return _turn(_slot_of(_newest(session)) if adapter.slots > 1 else 1)

def _named_in(number: int, host: str) -> str:
    return slot.named(host, number) if host in settings.RANGE.hosts else host

def _renamed(one, pairs):
    return [(_named_in(getattr(one, "slot", 1), host), held) for host, held in pairs]

def _of_slot(number: int):
    return Q(session__slot=number) | (Q(session__slot=None) if number == 1 else Q(pk__in=[]))
SUPPRESSION_LONGEST = 24 * 60
CASE_REQUIRED = ("case_id", "name", "malicious", "correlation", "started_at", "ended_at")

def _shape(obj, fields):
    return {name: getattr(obj, name) for name in fields}

def _request_of(raw):
    http = raw.get("http") or {}
    if http or raw.get("dest_ip"):
        return (http.get("http_method") or "", http.get("url") or "",
                raw.get("dest_ip") or "", raw.get("dest_port"))
    request = raw.get("request") or {}
    return (request.get("method") or "", request.get("uri") or "",
            raw.get("host_ip") or "", raw.get("host_port"))

def _listed(session, detection, zones, located):
    method, path, dest_ip, dest_port = _request_of(detection.raw or {})
    return dict(
        _shape(detection, DETECTION_FIELDS),
        marker=site.shown_marker(session, detection.marker),
        dest_ip=dest_ip,
        dest_port=dest_port,
        method=method,
        path=path,
        **_place(detection.src_ip, zones, located),
    )

def _place(address, zones, located):
    zone = _zone_of(address, zones) if address else None
    geo = located.get(address) or {}
    return {
        "zone": zone["name"] if zone else "",
        "outside": bool(zone and zone["outside"]),
        "country": geo.get("country_name") or "",
        "city": geo.get("city_name") or "",
    }

def _located(detections):
    located = {}
    for address, geo in detections.values_list("src_ip", "raw__src_geo"):
        if address and geo:
            located.setdefault(address, geo)
    return located

def _reply(payload, status=200):
    return JsonResponse(payload, status=status, safe=False)

def _payload(request):
    try:
        body = json.loads(request.body or b"{}")
    except ValueError as exc:
        raise BadRequest(f"the body is not JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise BadRequest(f"the body must be a JSON object, got {type(body).__name__}")
    return body

def _rule_file(request) -> str:
    content = _payload(request).get("content")
    if not isinstance(content, str):
        raise BadRequest(
            f'"content" must be the whole rule file as a string, got {content!r}'
        )
    return content

def _refuse_closed(session):
    if session.ended_at is not None:
        raise Conflict(f"session {session.pk} closed at {session.ended_at.isoformat()}")

SESSION_PAGE = 25

@require_http_methods(["GET", "POST"])
def sessions(request):
    if request.method == "GET":
        try:
            limit = max(1, min(SESSION_PAGE, int(request.GET.get("limit", SESSION_PAGE))))
        except ValueError:
            limit = SESSION_PAGE

        found = Session.objects.order_by("-id")
        state = request.GET.get("state")
        if state == "open":
            found = found.filter(ended_at=None)
        elif state == "closed":
            found = found.exclude(ended_at=None)
        if request.GET.get("ids") is not None:
            found = found.filter(pk__in=_asked_ids(request.GET["ids"]))

        return _reply([_described(s, judged=s.ended_at is not None) for s in found[:limit]])

    body = _payload(request)
    scenario = body.get("scenario")
    if scenario is None:
        scenario = "board"
    played = scenario if wargames.scenario_owner(scenario) else ""
    if played:
        scenario, guidance, taught, defense, posture = scenario_run.settings_for(played, body)
        mode = MODES[0]
    elif not isinstance(scenario, str) or scenario not in wargames.WARGAMES:
        raise BadRequest(
            f"{scenario!r} is not a wargame or a scenario; expected one of {', '.join(wargames.WARGAMES)}"
        )
    else:
        guidance, taught, defense, posture = _settings(scenario, body)
        mode = _mode(body, guidance, scenario, taught)
    adapter = substrate()
    with SLOT_CHOICE:
        live = list(Session.objects.filter(ended_at=None).values_list("pk", flat=True))
        if len(live) >= getattr(adapter, "max_sessions", 1):
            raise Conflict(
                f"{len(live)} {'session is' if len(live) == 1 else 'sessions are'} "
                f"already open on the range; close one first"
            )
        chosen = None
        if hasattr(adapter, "plan_slot"):
            verdict = _readiness(adapter, first_ready=True)
            if not verdict["ready"]:
                raise Conflict(
                    "the range is not ready: " + "; ".join(verdict["slot"]["blocked"])
                )
            chosen = verdict["slot"].get("number") if _slotted(adapter) else None
        try:
            session = Session.objects.create(
                scenario=scenario, baseline=[], guidance=guidance, lesson=taught, mode=mode, defense=defense, slot=chosen,
                course_scenario=played,
            )
        except IntegrityError:
            raise Conflict(f"slot {chosen} was taken by another session as this one opened; try again")
    try:
        if hasattr(adapter, "open_session"):
            adapter.open_session(session.pk, live=_stacks_to_keep(session))
        adapter = _range(session, adapter)
        _aim_attacker(adapter)
        _take_defense(session, adapter, posture)
        session.baseline = _baseline(adapter, scenario)
        if hasattr(adapter, "for_session") and not session.baseline \
                and wargames.objective_model(scenario) == "loot_verified":
            raise loot.GroundTruthUnavailable(
                f"the {scenario} target's accounts could not be read at open, so "
                f"nothing it loses could be checked; the session is closed"
            )
        session.save(update_fields=["baseline", "waf"])
        if guidance and not played:
            _seed_logs(session)
        session.ready_at = timezone.now()
        session.save(update_fields=["ready_at"])
        if played:
            scenario_run.begin(session, adapter, posture)
    except (harness.ToolUnavailable, loot.GroundTruthUnavailable, traffic.NoOrigin, RangeUnavailable) as exc:
        Session.objects.filter(pk=session.pk).update(ended_at=timezone.now())
        return _reply({"detail": str(exc)}, status=503)
    except Exception:
        Session.objects.filter(pk=session.pk).update(ended_at=timezone.now())
        raise
    return _reply(_described(session), status=201)

def _asked_ids(given):
    try:
        return [int(one, 10) for one in given.split(",") if one.strip()]
    except ValueError:
        raise BadRequest(f'"ids" must be session ids separated by commas, got {given!r}')

def _stacks_to_keep(opening):
    shipping = timezone.now() - STACK_OUTLIVES_ITS_SESSION
    return Session.objects.filter(
        Q(ended_at=None) | Q(ended_at__gte=shipping)
    ).exclude(pk=opening.pk).order_by("pk").values_list("pk", flat=True)

def _described(session, judged=False):
    return _shape(session, SESSION_FIELDS) | {
        "kind": "scenario" if session.course_scenario else "lesson" if session.guidance else "wargame",
        "course_scenario": session.course_scenario or None,
        "lesson_id": _lesson_id(session),
        "ready": session.ready_at is not None,
        **({"result": _result(session)} if judged else {}),
    }

def _result(session):
    inputs = _result_inputs(session)
    held = session.result_cache or {}
    if held.get("inputs") == inputs:
        return held["result"]
    result = _judged(session)
    Session.objects.filter(pk=session.pk).update(result_cache={"inputs": inputs, "result": result})
    return result

def _result_inputs(session):
    detections = session.detections.aggregate(last=Max("id"), rows=Count("id"), marked=Count("marker"))
    cases = session.cases.aggregate(last=Max("id"), rows=Count("id"))
    objectives = session.objectives.aggregate(last=Max("id"), rows=Count("id"))
    windows = (session.scenario_state or {}).get("windows") or []
    return [session.ended_at and session.ended_at.isoformat(), len(session.hints or []),
            *detections.values(), *cases.values(), *objectives.values(),
            [window.get("result") and window["result"]["passed"] for window in windows]]

def _judged(session):
    cases, _, result, _ = _evidence(session)
    breaches = _breaches(session, cases, result)
    runs = list(dict.fromkeys(
        case.meta["verify"] for case in session.cases.all() if case.meta.get("verify")
    ))
    return {
        "objectives": {
            "lost": len(breaches),
            "undetected": sum(1 for breach in breaches if not breach.detected),
            "total": len(wargames.objectives(session.scenario)["tiers"])
            if wargames.judged(session.scenario) else 0,
        },
        "lesson": dict(_last_verdict(session, runs[-1], len(runs)), helped=_helped(session)) if runs else None,
        "scenario": _scenario_result(session),
    }

def _scenario_result(session):
    judged = [window["result"] for window in (session.scenario_state or {}).get("windows") or [] if window.get("result")]
    if not judged:
        return None
    return {"passed": judged[-1]["passed"], "fix": judged[-1]["fix"], "windows": len(judged), "helped": _helped(session)}

def _helped(session):
    return [level for level in HINT_LEVELS if any(hint.get("level") == level for hint in session.hints or [])]

@require_http_methods(["POST"])
def lesson_hints(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    _refuse_closed(session)
    taught = _taught(session)
    _refuse_self(session)
    body = _payload(request)
    steps = [step["id"] for step in taught.get("steps", [])]
    step, level = body.get("step"), body.get("level")
    if step not in steps:
        raise BadRequest(f'"step" must be one of {steps}, got {step!r}')
    if level not in HINT_LEVELS:
        raise BadRequest(f'"level" must be one of {list(HINT_LEVELS)}, got {level!r}')
    session = _progressed(session, step, lambda kept, held: _helped_on(kept, held, step, level))
    return _reply(_lesson_state(session, step))

def _lesson_of(session):
    try:
        return wargames.lesson(session.scenario, lesson_id=session.lesson or None)
    except wargames.UnknownWargame:
        return None

def _lesson_id(session):
    taught = _lesson_of(session) if session.guidance else None
    return taught["id"] if taught else None

def _taught(session):
    taught = _lesson_of(session) if session.guidance else None
    if not taught:
        raise BadRequest(f"session {session.pk} is not a lesson")
    return taught

def _taught_step(session, step_id):
    taught = _taught(session)
    for step in taught.get("steps", []):
        if step["id"] == step_id:
            return taught, step
    raise Http404(f"the lesson has no step {step_id!r}")

def _progressed(session, step_id, change):
    with transaction.atomic():
        held = Session.objects.select_for_update().get(pk=session.pk)
        kept = dict(held.lesson_steps.get(step_id) or {})
        change(kept, held)
        held.lesson_steps = {**held.lesson_steps, step_id: kept}
        held.save(update_fields=["lesson_steps", "hints"])
    return held

def _helped_on(kept, held, step_id, level):
    used = {"step": step_id, "level": level}
    if used not in held.hints:
        held.hints = [*held.hints, used]
    if level == "do":
        kept["done_for_me"] = True
    else:
        kept["hint"] = min(lesson.DO_IT, kept.get("hint", 0) + 1)

def _progress(session):
    taught = _lesson_of(session) if session.guidance and session.lesson_steps else None
    declared = {step["id"]: step for step in (taught or {}).get("steps", [])}
    return {
        step_id: {"reached": kept.get("reached"), "passed": kept.get("passed"), "skipped": kept.get("skipped"),
                  "hint": kept.get("hint", 0), "done_for_me": bool(kept.get("done_for_me")),
                  **_revealed(session, taught, declared.get(step_id), kept)}
        for step_id, kept in session.lesson_steps.items()
    }

def _revealed(session, taught, step, kept):
    if not step:
        return {}
    named = f"{taught['text']}.{{}}.{step['id']}"
    return {
        **({"answer": strings.both(named.format("answer"))} if kept.get("hint", 0) >= lesson.ANSWER else {}),
        **({"line": strings.both(named.format("line"))} if kept.get("passed") else {}),
        **({"command": _command_of(session, step)} if _command_shown(session, step) else {}),
    }

def _command_of(session, step):
    if step["check"]["kind"] != "kali":
        return step.get("command") or ""
    marker = (session.lesson_steps.get(step["id"]) or {}).get("marker")
    return _kali_command(session, step["check"]["case"], marker) if marker else ""

def _kali_command(session, name, marker):
    case = dict(wargames.find_case(session.scenario, name), case_id=marker, correlation="marker")
    return shlex.join(tools.tool_argv(case, wargames.WARGAMES[session.scenario]["public_url"])[1])

def _command_shown(session, step):
    reached = (session.lesson_steps.get(step["id"]) or {}).get("reached")
    return bool(_command_of(session, step)) and session.mode != "self" and bool(reached)

def _lesson_state(session, step_id, **judged):
    return {**judged, "hint": session.lesson_steps.get(step_id, {}).get("hint", 0),
            "hints": session.hints, "progress": _progress(session)}

@require_http_methods(["POST"])
def lesson_step(request, session_id, step_id):
    session = get_object_or_404(Session, pk=session_id)
    _refuse_closed(session)
    _, taught_step = _taught_step(session, step_id)
    armed = taught_step["check"]["kind"] == "kali"
    state = _payload(request).get("state")
    if state not in LESSON_STEP_STATES:
        raise BadRequest(f'"state" must be one of {list(LESSON_STEP_STATES)}, got {state!r}')
    now = timezone.now().isoformat()
    newest = session.detections.aggregate(last=Max("id"))["last"] or 0

    def mark(kept, held):
        if state == "reached":
            kept.setdefault("reached", now)
            kept["after"] = newest
            if armed:
                kept.setdefault("marker", str(uuid.uuid4()))
        elif not kept.get("passed"):
            kept["skipped"] = now

    return _reply(_lesson_state(_progressed(session, step_id, mark), step_id))

@require_http_methods(["POST"])
def lesson_step_check(request, session_id, step_id):
    session = get_object_or_404(Session, pk=session_id)
    _refuse_closed(session)
    taught, step = _taught_step(session, step_id)
    body = _payload(request)
    poll = body.get("poll") is True
    kept = session.lesson_steps.get(step_id) or {}
    try:
        passed, reason, tried, *seen = _judge(session, taught, step, body, poll, kept)
    except harness.ToolUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)
    return _reply(_judged_step(session, step_id, passed, reason, poll, tried) | dict(*seen))

@require_http_methods(["POST"])
def lesson_step_do(request, session_id, step_id):
    session = get_object_or_404(Session, pk=session_id)
    _refuse_closed(session)
    taught, step = _taught_step(session, step_id)
    _refuse_self(session)
    session = _progressed(session, step_id, lambda kept, held: _helped_on(kept, held, step_id, "do"))
    check = step["check"]
    try:
        if check["kind"] in ("answer", "choice"):
            accepted = _accepted(session, check, taught)
            if not accepted:
                return _reply(_judged_step(session, step_id, False, ["lesson.check.unrecorded", []], True, None))
            passed, reason, tried = _judge(session, taught, step, {"answer": accepted[0]}, False, {})
        elif check["kind"] == "waf":
            _put_exclusion(session, check)
            passed, reason, tried, *_ = _judge(session, taught, step, {}, False, {})
        elif check["kind"] == "level":
            _put_level(session, taught)
            passed, reason, tried, *_ = _judge(session, taught, step, {}, False, {})
        elif check["kind"] == "rules":
            _put_rule(session, step)
            passed, reason, tried, *_ = _judge(session, taught, step, {}, False, {})
        elif check["kind"] == "kali":
            session = _kali_do(session, step)
            passed, reason, tried, *_ = _judge(session, taught, step, {}, False, session.lesson_steps[step_id])
        elif check["kind"] == "loot":
            _loot_do(session, check)
            passed, reason, tried, *_ = _judge(session, taught, step, {}, False, {})
        elif check["kind"] in ("click", "served", "replay", "detect", "sent"):
            passed, reason, tried, *_ = _judge(session, taught, step, {}, False, {})
        else:
            return _reply(_lesson_state(session, step_id, passed=False, reason=None))
    except harness.ToolUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)
    return _reply(_judged_step(session, step_id, passed, reason, True, tried))

def _put_exclusion(session, check):
    wanted = {"rule_id": check["rule_id"], "target": check["target"], "path": check["path"]}
    with _turn_of(session):
        standing = _waf_in_force(session)
        exclusions = [entry for entry in standing["exclusions"] if entry != wanted] + [wanted]
        session.waf = crs.apply({"paranoia": standing["paranoia"] or 1, "exclusions": exclusions,
                                 **_thresholds_of(standing)}, _range(session).runner("gateway"), settings.FSL_WAF)
        session.save(update_fields=["waf"])

def _put_level(session, taught):
    posture = _posture(session)
    with _turn_of(session):
        session.waf = crs.apply({**posture, "paranoia": taught["solved_at"]["paranoia"]},
                                _range(session).runner("gateway"), settings.FSL_WAF)
        session.save(update_fields=["waf"])

def _put_rule(session, step):
    with _turn_of(session):
        live = _live_rules(session)
        _apply(f"{live.rstrip()}\n{step['rule'].strip()}\n", session)

def _posture(session):
    declared = (wargames.WARGAMES[session.scenario].get("defense") or {}).get(session.defense)
    return crs.checked(declared["waf"]) if declared else {"paranoia": lesson.CRS_DEFAULT_LEVEL, "exclusions": []}

def _posture_rules(session):
    declared = (wargames.WARGAMES[session.scenario].get("defense") or {}).get(session.defense) or {}
    return (Path(settings.FSL_SOURCE) / "deploy/suricata/rules" / declared.get("suricata", DEFAULT_RULES)).read_text()

def _judged_step(session, step_id, passed, reason, poll, tried):
    now = timezone.now().isoformat()

    def mark(kept, held):
        if tried is not None:
            kept["tried"] = tried
        if passed:
            kept.setdefault("passed", now)
            return
        if poll:
            return
        kept["wrong"] = kept.get("wrong", 0) + 1
        if kept["wrong"] >= lesson.WRONGS_PER_HINT:
            kept["wrong"] = 0
            stuck.append(step_id)
            if not held.course_scenario:
                _helped_on(kept, held, step_id, "hint")

    stuck = []
    session = _progressed(session, step_id, mark)
    if stuck:
        scenario_run.stuck(session, "check", step_id)
    return _lesson_state(session, step_id, passed=passed, reason=None if passed else reason)

def _judge(session, taught, step, body, poll, kept):
    check, prefix, step_id = step["check"], taught["text"], step["id"]
    failed = f"{prefix}.fail.{step_id}"
    kind = check["kind"]
    if kind == "click":
        return True, None, None
    if kind in ("answer", "choice"):
        given = body.get("answer")
        if not isinstance(given, str) or not given.strip():
            raise BadRequest(f'"answer" must be the text given for step {step_id!r}, got {given!r}')
        accepted = _accepted(session, check, taught)
        if not accepted:
            return False, ["lesson.check.unrecorded", []], None
        passed, reason = lesson.answered(dict(check, accept=accepted), given.strip(), f"{prefix}.wrong.{step_id}")
        return passed, reason, None
    if kind == "level":
        refused = lesson.level_refused(_waf_in_force(session), _posture(session))
        return refused is None, [f"{failed}.{refused}" if refused else failed, []], None
    if kind == "rules":
        added = lesson.added_rules(_live_rules(session), _posture_rules(session))
        return bool(added), [failed, []], None, {"added": added}
    if kind == "detect":
        return _detect_check(session, taught, check, step_id, failed)
    if kind == "alert":
        return _alert_seen(session, check, kept.get("after", 0)), [failed, []], None
    if kind == "served":
        status = _check_replay(session, check["case"], step_id)
        return lesson.served(status), [failed, [status or "-"]], None
    if kind == "replay":
        return _replay_check(session, check, step_id, failed)
    if kind == "sent":
        return bool(_site_requests(session, check)), [failed, []], None
    if kind == "kali":
        return _kali_check(session, step, kept, failed)
    if kind == "loot":
        return _loot_check(session, check, body.get("answer"), failed)
    if kind == "triage":
        return scenario_run.triage_passed(session, check["judged"]), [failed, []], None
    if kind == "waf":
        return _waf_check(session, check, step_id, poll, kept, failed)
    runs = list(dict.fromkeys(case.meta["verify"] for case in session.cases.all() if case.meta.get("verify")))
    return bool(runs) and _verified(session, runs[-1])["passed"], [f"{prefix}.fail.verify", []], None

def _waf_check(session, check, step_id, poll, kept, failed):
    standing = _waf_in_force(session)
    fixed = {"fix": _fix(session, standing)}
    wanted = {"rule_id": check["rule_id"], "target": check["target"], "path": check["path"]}
    if wanted not in standing["exclusions"]:
        return False, [failed, []], None, fixed
    if not check.get("case"):
        return True, None, None, fixed
    version = _version(json.dumps(standing, sort_keys=True))
    if poll and kept.get("tried") == version:
        return False, [f"{failed}.reload", []], None, fixed
    served = lesson.served(_check_replay(session, check["case"], step_id))
    return served, [f"{failed}.reload", []], version, fixed

def _replay_check(session, check, step_id, failed):
    recorded, _ = _lesson_fire(session, check["case"], {"check": step_id})
    outcome = lesson.outcome(_row(session, recorded))
    shown = {"replay": _replay_row(session, recorded)}
    if outcome == check["expect"]:
        return True, None, None, shown
    if outcome == "inconclusive":
        return False, ["lesson.check.inconclusive", [check["case"]]], None, shown
    return False, [failed, []], None, shown

def _accepted(session, check, taught=None):
    if "of" not in check:
        return check["accept"]
    if check["of"] in wargames.RANGE_FACTS:
        return _range_fact(session, check["of"])
    if check["of"] in wargames.REQUEST_FACTS:
        about = _taught_check(taught, check["about"])
        record = (_site_requests(session, about) or [None])[-1]
        return _request_fact(session, record, check["of"]) if record else []
    if check["of"] in wargames.KALI_FACTS:
        return _kali_fact(session, check["about"], check["of"])
    _ingest(session, RECENT_ALERTS)
    marker = session.browse_marker if check.get("marker") == SITE_BROWSER_MARKER else check.get("marker")
    found = session.detections.filter(source="modsecurity", **({"marker": marker} if marker else {}))
    return lesson.read_from(check["of"], [
        detection.raw or {} for detection in found
        if check["path"] in unquote(_request_of(detection.raw or {})[1])
    ])

def _taught_check(taught, step_id):
    return next(step["check"] for step in taught.get("steps", []) if step["id"] == step_id)

def _site_requests(session, check):
    pattern = re.compile(check["match"])
    return [record for record in site.kept(session.pk) if pattern.search(unquote(record["url"].replace("+", " ")))]

def _range_fact(session, of):
    if of == "lost":
        return [str(_result(session)["objectives"]["lost"])]
    if of == "excluded":
        return [str(entry["rule_id"]) for entry in _waf_in_force(session)["exclusions"]]
    return topology.facts(gns3.local(), settings.RANGE, session.scenario)[of]

def _request_fact(session, record, of):
    url = urlsplit(record["url"])
    if of in ("status", "status_class", "method", "path", "parameter"):
        return {"status": [str(record["status"])], "status_class": [f"{record['status'] // 100}xx"],
                "method": [record["method"]], "path": list(dict.fromkeys([url.path, url.path.rstrip("/") or "/"])),
                "parameter": sorted(parse_qs(url.query, keep_blank_values=True))}[of]
    if of in ("source", "stopped_at"):
        followed = _followed(session, record=record)
        if of == "source":
            return [followed["address"]] if followed["address"] else []
        return [hop["node"] for hop in followed["hops"] if hop.get("verdict") == "blocked"]
    if of in ("port", "sensor_source"):
        events = _sensed_for(session, record)
        if of == "sensor_source":
            return sorted({str(event["src_ip"]) for event in events if event.get("src_ip")})
        return list(dict.fromkeys([str(url.port or 80), *(str(event["dest_port"]) for event in events
                                                           if event.get("dest_port"))]))
    _ingest(session, RECENT_ALERTS)
    recorded = list(_browsed(session, record))
    if of == "waf_source":
        return sorted({detection.src_ip for detection in recorded if detection.source == "modsecurity" and detection.src_ip})
    heard = {detection.source for detection in recorded} | ({"suricata"} if _sensed_for(session, record) else set())
    return sorted(heard)

def _window_of(record):
    start = datetime.fromtimestamp(record["at"], tz=dt_timezone.utc)
    return start - FOLLOW_SLACK, start + timedelta(milliseconds=record.get("ms") or 0) + FOLLOW_SLACK

def _browsed(session, record):
    start, end = _window_of(record)
    return session.detections.filter(marker=session.browse_marker, timestamp__gte=start, timestamp__lte=end)

def _sensed_for(session, record):
    start, end = _window_of(record)
    asked = urlsplit(record["url"])
    return _sensed(session, start, end, session.browse_marker, asked.path + (f"?{asked.query}" if asked.query else ""))

def _sensed(session, start, end, marker, path=""):
    try:
        documents, _ = _fetched(_session_index(session) or settings.ELASTIC_INDEX, start, end, newest_first=False)
    except elastic.ElasticUnavailable:
        return []
    found = []
    for _, doc in documents:
        http = doc.get("http") or {}
        if doc.get("fsl_source") != "suricata" or doc.get("event_type") != "http":
            continue
        labelled = elastic.suricata_marker(http)
        if labelled == marker or (path and not labelled and http.get("url") == path):
            found.append(doc)
    return found

def _counted(events):
    by_sensor = {}
    for event in events:
        said = str(((event.get("log") or {}).get("syslog") or {}).get("hostname") or "").split(".")[0]
        by_sensor[said] = by_sensor.get(said, 0) + 1
    return max(by_sensor.values(), default=0), by_sensor

def _kali_check(session, step, kept, failed):
    marker = kept.get("marker")
    if not marker:
        return False, [failed, []], None
    case = wargames.find_case(session.scenario, step["check"]["case"])
    recorded = session.cases.filter(case_id=marker).first()
    reached = parse_datetime(kept.get("reached") or "") or session.started_at
    events = _sensed(session, reached - FOLLOW_SLACK, timezone.now() + FOLLOW_SLACK, marker)
    ran = [event for event in events if case["tool"] in str((event.get("http") or {}).get("http_user_agent", "")).lower()]
    count, by_sensor = _counted(events)
    shown = {"kali": {"name": case["name"], "requests": count, "sensors": by_sensor,
                      "discover": _discover(session, kibana.sensed_http(marker), everything=True)}}
    if recorded is None and not ran:
        return False, ["lesson.check.kali_none", [case["tool"]]], None, shown
    if recorded is None:
        first = min((parse_datetime(str(event.get("timestamp") or "")) for event in ran), default=None) or reached
        _record_case(session, dict(case, case_id=marker, correlation="marker"), first, timezone.now(),
                     {"kali": step["id"], "launched_on": settings.RANGE.default_origin,
                      "command": _kali_command(session, case["name"], marker)})
        _settle_and_observe(session)
        try:
            _ingest(session)
        except elastic.ElasticUnavailable:
            pass
    return True, None, None, shown

def _kali_do(session, step):
    name = step["check"]["case"]
    recorded, _ = _fire(session, name, None, lambda ran: {
        "kali": step["id"], "done_for_me": True, "dumped": tools.dumped(ran.output),
        "conclusions": tools.conclusions(ran.output)})
    return _progressed(session, step["id"], lambda kept, held: kept.update(marker=recorded.case_id))

def _kali_case(session, step_id):
    marker = (session.lesson_steps.get(step_id) or {}).get("marker")
    return session.cases.filter(case_id=marker).first() if marker else None

def _kali_fact(session, step_id, of):
    recorded = _kali_case(session, step_id)
    if recorded is None:
        return []
    if of == "leaked":
        return [str(len(recorded.meta["loot"]))] if "loot" in recorded.meta else []
    count, _ = _counted(_sensed(session, recorded.started_at - FOLLOW_SLACK, timezone.now(), recorded.case_id))
    return [str(found) for found in lesson.within(count, COUNT_TOLERANCE)]

def _loot_check(session, check, given, failed):
    recorded = _kali_case(session, check["about"])
    if recorded is None:
        return False, ["lesson.check.loot_no_run", []], None
    if isinstance(given, str) and given.strip():
        _credit_loot(session, lesson.pasted_rows(given, tools.dumped(given)), recorded.case_id)
        recorded.refresh_from_db()
    matched = recorded.meta.get("loot") or []
    return bool(matched), [failed, []], None, {"loot": {"matched": matched}}

def _loot_do(session, check):
    recorded = _kali_case(session, check["about"])
    if recorded is not None and recorded.meta.get("dumped"):
        _credit_loot(session, recorded.meta["dumped"], recorded.case_id)

def _detect_check(session, taught, check, step_id, failed):
    recorded, _ = _lesson_fire(session, check["case"], {"check": step_id})
    row = _detection_rows(session, taught, [recorded], watch=True)[0]
    found = lesson.detection_outcome(row)
    shown = {"detected": {"name": recorded.name, "outcome": found, "verdict": lesson.scored(row),
                          "signatures": row["alerts"], "discover": _discover(session, kibana.sensed(recorded.case_id))}}
    wanted = ("detected",) if check["expect"] == "alert" else ("quiet",)
    if found in wanted:
        return True, None, None, shown
    return False, [f"lesson.check.{found}", [recorded.name, row["expect"]]], None, shown

def _detection_rows(session, taught, cases, watch=False):
    expected = wargames.expectations(session.scenario)
    wanted = [case.case_id for case in cases if case.malicious]
    deadline = time.monotonic() + settings.LESSON_ALERT_WAIT
    while True:
        if watch:
            _ingest(session, RECENT_ALERTS)
        alerts = _alerts_by_case(session, taught, cases)
        if not watch or time.monotonic() >= deadline or (wanted and all(alerts.get(case_id) for case_id in wanted)):
            break
        time.sleep(settings.LESSON_ALERT_POLL)
    indiscriminate = {signature for case in cases if not case.malicious for signature in alerts.get(case.case_id, [])}
    return [
        {"name": case.name, "malicious": case.malicious, "alerts": alerts.get(case.case_id, []),
         "expect": expected.get(case.name, ""),
         "corroborated": scoreboard.corroborated(expected.get(case.name), alerts.get(case.case_id, []), indiscriminate)}
        for case in cases
    ]

def _alerts_by_case(session, taught, cases):
    found = session.detections.filter(source=taught["detected_by"], marker__in=[case.case_id for case in cases])
    alerts = {}
    for detection in found:
        alerts.setdefault(detection.marker, [])
        if detection.signature not in alerts[detection.marker]:
            alerts[detection.marker].append(detection.signature)
    return alerts

def _replay_row(session, recorded):
    meta = recorded.meta
    return {
        "name": recorded.name,
        "outcome": lesson.outcome(_row(session, recorded)),
        "conclusions": meta.get("conclusions") or [],
        "command": " ".join([meta["tool"], *meta.get("args", [])]) if meta.get("tool") else "",
        "forbidden": meta.get("forbidden", 0),
        "status": meta.get("status", 0),
        "discover": _discover(session, kibana.marked(recorded.case_id)),
    }

def _fix(session, waf):
    taught = (_lesson_of(session) if session.guidance else None) or {}
    scope = next((step["check"].get("path", "") for step in taught.get("steps", []) if step["check"]["kind"] == "waf"), "")
    declared = (wargames.WARGAMES[session.scenario].get("defense") or {}).get(session.defense)
    return lesson.fix_class(waf, crs.checked(declared["waf"]) if declared else None, scope)

def _check_replay(session, name, step_id):
    recorded, _ = _lesson_fire(session, name, {"check": step_id})
    return int(recorded.meta.get("status") or 0)

def _alert_seen(session, check, after):
    _ingest(session, RECENT_ALERTS)
    marker = session.browse_marker if check.get("marker") == SITE_BROWSER_MARKER else check.get("marker")
    return any(
        check.get("path", "") in unquote(_request_of(detection.raw or {})[1])
        for detection in session.detections.filter(id__gt=after, marker=marker)
    )

def _last_verdict(session, run, verified):
    judged = _verified(session, run)
    return {"passed": judged["passed"], "verified": verified, "diagnosis": judged["diagnosis"],
            "mode": judged["mode"], "fix": judged["fix"]}

def _settings(scenario, body):
    asked = body.get("lesson")
    guidance = body.get("guidance", asked is not None)
    if not isinstance(guidance, bool):
        raise BadRequest(f'"guidance" must be true or false, got {guidance!r}')
    if guidance and not wargames.lesson(scenario):
        raise BadRequest(f"{scenario!r} has no lesson to guide")
    taught = _asked_lesson(scenario, asked) if guidance else ""
    if asked is not None and not guidance:
        raise BadRequest(f'"lesson" {asked!r} runs with guidance; leave "guidance" out or send true')
    defense = body.get("defense", wargames.lesson_defense(scenario, taught) if guidance else wargames.DEFAULT_DEFENSE)
    try:
        return guidance, taught, defense, wargames.defense(scenario, defense)
    except (wargames.UnknownWargame, TypeError):
        raise BadRequest(
            f"{defense!r} is not a defense of {scenario!r}; expected one of "
            f"{', '.join(wargames.WARGAMES[scenario].get('defense') or [wargames.DEFAULT_DEFENSE])}"
        )

def _mode(body, guidance, scenario="", taught=""):
    mode = body.get("mode", wargames.lesson_mode(scenario, taught) if guidance else MODES[0])
    if mode not in MODES:
        raise BadRequest(f'"mode" must be one of {list(MODES)}, got {mode!r}')
    if mode != MODES[0] and not guidance:
        raise BadRequest(f'"mode" {mode!r} is a way to run a lesson; a wargame has no guidance to leave out')
    return mode

def _refuse_self(session):
    if session.mode == "self":
        raise Conflict(f"session {session.pk} runs the lesson in self mode, which gives no help; "
                       f"PATCH its mode to guided first")

def _asked_lesson(scenario, asked):
    known = wargames.taught_ids(scenario)
    if asked is None:
        return wargames.lesson(scenario)["id"]
    if asked not in known:
        raise BadRequest(f'"lesson" must be one of {scenario!r}\'s lessons {known}, got {asked!r}')
    return asked

def _take_defense(session, adapter, posture):
    ruleset = (posture or {}).get("suricata", DEFAULT_RULES)
    checked_at_baseline_when_ready = _slotted(adapter) and ruleset == DEFAULT_RULES
    if not checked_at_baseline_when_ready:
        rules = (Path(settings.FSL_SOURCE) / "deploy/suricata/rules" / ruleset).read_text()
        for runner, reload_command, path in _sensors(adapter):
            suricata.seed(rules, runner, reload_command, path)
    if posture is not None:
        session.waf = crs.apply(posture["waf"], adapter.runner("gateway"), settings.FSL_WAF)

def _seed_logs(session):
    for name in _lesson_of(session)["cases"]:
        _lesson_fire(session, name, {"seed": True})

def _aim_attacker(adapter):
    attacker.wear_origin(
        attacker.find(Shape(segments=adapter.segments(), sensors=()), None),
        adapter.runner("proxy"),
    )

def _baseline(adapter, scenario):
    model = wargames.objective_model(scenario)
    if model == "loot_verified":
        try:
            return _ground_truth(adapter, scenario)
        except loot.GroundTruthUnavailable:
            return None
    if model == "effect_observed":
        try:
            return effect.snapshot(adapter.runner("corp-db"))
        except (effect.StateUnavailable, RangeUnavailable):
            return None
    return []

def _ground_truth(adapter, wargame_id):
    try:
        host = adapter.address("board") if hasattr(adapter, "address") else ""
    except RangeUnavailable as exc:
        raise loot.GroundTruthUnavailable(str(exc)) from exc
    return loot.ground_truth(wargame_id, host)

def _newest(session=None):
    return session or Session.objects.order_by("-id").first()

def _range(session=None, adapter=None):
    adapter = adapter or substrate()
    if _slotted(adapter):
        return adapter.in_slot(_slot_of(_newest(session)) if adapter.slots > 1 else 1)
    if not hasattr(adapter, "for_session"):
        return adapter
    session = _newest(session)
    return adapter.for_session(session.pk if session else None)

def _asked_session(request):
    given = request.GET.get("session")
    if given is None and request.method == "POST":
        given = _payload(request).get("session")
    if given in (None, ""):
        return None
    try:
        wanted = int(given)
    except (TypeError, ValueError, OverflowError):
        raise BadRequest(f'"session" must be a session id, got {given!r}')
    return get_object_or_404(Session, pk=wanted)

def _written(request):
    asked = _asked_session(request)
    if asked:
        _refuse_closed(asked)
        return asked
    adapter = substrate()
    if not hasattr(adapter, "for_session") and getattr(adapter, "slots", 1) <= 1:
        return None
    found = Session.objects.filter(ended_at=None).order_by("-id").first()
    if found is None:
        raise Conflict("no session is open; open one, or name the session to act on")
    return found

def _terminal_url(session):
    if settings.ATTACKER_SESSION_TERMINAL_URL and session:
        return settings.ATTACKER_SESSION_TERMINAL_URL.format(session=session.pk)
    return settings.ATTACKER_TERMINAL_URL

@require_http_methods(["GET"])
def attacker_box(request):
    session = _newest(_asked_session(request))
    origin = attacker.find(_standing(session), request.GET.get("origin"))
    return _reply(
        {
            "container": settings.ATTACKER_CONTAINER,
            "source_ip": origin["source_ip"],
            "direct_ip": origin["direct_ip"],
            "origin": origin["id"],
            "origin_label": origin["label"],
            "target_url": origin["target_url"],
            "public_url": settings.PUBLIC_TARGET_URL,
            "terminal_url": _terminal_url(session),
        }
    )

TOP_N = 25

def _standing(session=None):
    return Shape(segments=_range(session).segments(), sensors=())

def _segments(session=None, recent=False):
    key = (session.pk, session.started_at) if session and recent else None
    held = _segments_kept.get(key) if key else None
    if held and time.monotonic() - held[0] < SEGMENTS_KEPT_FOR:
        return held[1]
    try:
        standing = _standing(session)
    except RangeUnavailable:
        return [], {}

    segments = topology.shape(standing, settings.RANGE)["segments"]

    hosts = {
        node["address"]: node["name"]
        for segment in segments
        for node in segment["nodes"]
        if node["address"]
    }
    if key:
        _segments_kept[key] = (time.monotonic(), (_zones(segments), hosts))
    return _zones(segments), hosts

def _zones(segments):
    zones = []
    for segment in segments:
        try:
            zones.append((ipaddress.ip_network(segment["subnet"]), segment))
        except ValueError:
            continue
    return zones

def _zone_of(address, zones):
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return None
    return next((s for network, s in zones if parsed in network), None)

@require_http_methods(["GET"])
def session_top(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    detections = list(session.detections.all())
    zones, hosts = _segments(session)
    located = _located(session.detections)

    sources, destinations, signatures, paths = {}, {}, {}, {}

    def count(table, key, row):
        if key not in table:
            table[key] = dict(row(), alerts=0)
        table[key]["alerts"] += 1

    for detection in detections:
        method, url, dest_ip, port = _request_of(detection.raw or {})
        address = detection.src_ip
        if address:
            count(sources, address, lambda: {
                "src_ip": address,
                "host": detection.src_host,
                **_place(address, zones, located),
                "country_code": (located.get(address) or {}).get("country_iso_code") or "",
            })
        if dest_ip:
            count(destinations, (dest_ip, port), lambda: {
                "dest_ip": dest_ip,
                "dest_port": port,
                "host": detection.dest_host,
                "zone": _place(dest_ip, zones, {})["zone"],
            })
        count(signatures, (detection.signature, detection.source), lambda: {
            "signature": detection.signature,
            "engine": detection.source,
        })
        if url:
            count(paths, (method, url), lambda: {"method": method, "path": url})

    def top(rows):
        return sorted(rows, key=lambda r: -r["alerts"])[:TOP_N]

    return _reply({
        "sources": top(sources.values()),
        "destinations": top(destinations.values()),
        "signatures": top(signatures.values()),
        "paths": top(paths.values()),
    })

@require_http_methods(["GET"])
def range_topology(request):
    language = request.GET.get("language") or gns3.ENGLISH
    if language not in strings.LANGUAGES:
        raise BadRequest(f'"language" is one of {", ".join(strings.LANGUAGES)}, got {language!r}')
    return _reply(gns3.project(language))

def _drawn(session, described):
    number = _slot_of(session)
    return topology.overlay(gns3.local(), described, settings.RANGE,
                            lambda name: _named_in(number, name))

@require_http_methods(["GET"])
def session_topology(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    described = _range(session).describe()
    shape = topology.shape(described, settings.RANGE)

    for segment in shape["segments"]:
        segment["alerts"] = 0
    zones = _zones(shape["segments"])

    unplaced = 0
    for detection in session.detections.all():
        zone = _zone_of(detection.src_ip or "", zones)
        if zone is None:
            unplaced += 1
        else:
            zone["alerts"] += 1

    return _reply({**shape, "unplaced": unplaced, "project": _drawn(session, described)})

def _site_record(session, asked):
    try:
        wanted = int(asked, 10)
    except ValueError:
        raise BadRequest(f'"request" must be a Website pane request id, got {asked!r}')
    record = next((kept for kept in site.kept(session.pk) if kept["id"] == wanted), None)
    if record is None:
        raise Http404(f"session {session.pk} kept no request {wanted}")
    return record

def _sent(session, record, case):
    roles = settings.RANGE.roles
    if record:
        host = record["url"].split("/")[2].split(".")[0]
        return {"kind": "browse", "sender": roles["scorer"], "to": record.get("to") or "",
                "status": record.get("status"), "blocked": record.get("blocked"),
                "target": host if host in roles else "board"}
    target = session.scenario if session.scenario in roles else "board"
    if case:
        return {"kind": "case", "sender": roles["attacker"], "on": case.meta.get("launched_on") or "",
                "source": case.meta.get("source_ip") or "", "status": case.meta.get("status") or None,
                "blocked": case.meta.get("blocked"), "target": target}
    return {"kind": "marker", "sender": roles["proxy"], "target": target}

@require_http_methods(["GET"])
def session_follow(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    asked, fired = request.GET.get("request"), request.GET.get("case")
    record = _site_record(session, asked) if asked is not None else None
    case = None
    if fired and record is None:
        case = session.cases.filter(case_id=fired).first()
        if case is None:
            raise Http404(f"session {session_id} recorded no case {fired}")
    marker = request.GET.get("marker") or (SITE_BROWSER_MARKER if record else case.case_id if case else "")
    if not marker:
        raise BadRequest('name a "marker", a Website pane "request" or a fired "case" to follow')
    return _reply(_followed(session, record, case, marker))

def _followed(session, record=None, case=None, marker=SITE_BROWSER_MARKER):
    try:
        _ingest(session, RECENT_ALERTS)
    except elastic.ElasticUnavailable:
        pass
    stored = session.browse_marker if marker == SITE_BROWSER_MARKER else marker
    detections = session.detections.filter(marker=stored)
    if record:
        detections = _browsed(session, record)
        seen = _sensed_for(session, record)
    elif case:
        seen = _sensed(session, case.started_at - FOLLOW_SLACK, case.ended_at + FOLLOW_SLACK, stored)
    else:
        seen = []
    detections = list(detections)
    nodes = _drawn(session, _range(session).describe())["nodes"]
    number = _slot_of(session)
    followed = topology.follow(gns3.local(), settings.RANGE, nodes, _sent(session, record, case),
                               detections, lambda name: _named_in(number, name), seen)
    return {
        "marker": marker,
        "request": {name: record[name] for name in site.SUMMARY} if record else None,
        "case": {"case_id": case.case_id, "name": case.name} if case else None,
        "detections": len(detections),
        "sensed": len(seen),
        **followed,
    }

@require_http_methods(["GET"])
def origins(request):
    return _reply({"origins": attacker.origins(_standing(_asked_session(request)))})

@require_http_methods(["GET"])
def session_commands(request, session_id):
    session = get_object_or_404(Session, pk=session_id)

    typed = operator_log.commands(_range(session).runner("attacker"))
    return _reply({
        "commands": [
            {
                "at": command.at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "case_id": command.marker,
                "text": command.text,
            }
            for command in operator_log.within(
                typed, session.started_at, session.ended_at
            )
        ]
    })

@require_http_methods(["POST"])
def attacker_origin(request):
    session = _written(request)
    chosen = attacker.find(_standing(session), _payload(request).get("origin"))
    attacker.wear_origin(chosen, _range(session).runner("proxy"))
    return _reply({"origin": chosen["id"], "source_ip": chosen["source_ip"]})

@require_http_methods(["POST"])
def attacker_label(request):
    case_id = _payload(request).get("case_id")
    if case_id not in (None, "") and not (
        isinstance(case_id, str) and case_id.isprintable() and " " not in case_id
        and not case_id.startswith(RESERVED_MARKERS)
    ):
        raise BadRequest(
            '"case_id" must be one marker with no spaces or control characters, not starting '
            f"with {SITE_BROWSER_MARKER!r}, or null to clear the label, got {case_id!r}"
        )
    attacker.set_label(case_id or None, _range(_written(request)).runner("proxy"))
    return _reply({"ok": True})

@require_http_methods(["GET"])
def wargame_catalogue(request):
    return _reply(wargames.catalogue())

@require_http_methods(["GET"])
def wargame_cases(request, wargame_id):
    try:
        return _reply(wargames.cases(wargame_id))
    except wargames.UnknownWargame:
        raise Http404(wargame_id)

@require_http_methods(["GET"])
def wargame_objectives(request, wargame_id):
    if wargame_id not in wargames.WARGAMES:
        raise Http404(wargame_id)
    model = wargames.objective_model(wargame_id)
    if model == "none":
        return _reply([])
    return _reply(_loot_catalogue(wargames.objectives(wargame_id)))

def _loot_catalogue(spec):
    return [
        {
            "key": tier["key"],
            "name": tier["name"],
            "category": tier.get("category") or "",
            "difficulty": int(tier["difficulty"]),
            "description": tier.get("description") or "",
            "solved": False,
            "solved_at": None,
        }
        for tier in spec["tiers"]
    ]

@require_http_methods(["GET", "POST"])
def session_objectives(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    if request.method == "GET":
        return _reply(
            [_shape(o, OBJECTIVE_FIELDS) for o in session.objectives.all()]
        )
    _refuse_closed(session)
    return _reply(_observe_objectives(session))

def _observe_objectives(session) -> dict:
    model = wargames.objective_model(session.scenario)
    if model != "effect_observed":
        return {"achieved": 0, "total": session.objectives.count()}

    spec = wargames.objectives(session.scenario)
    total = len(spec["tiers"])
    try:
        changes = effect.read_changes(
            _range(session).runner("corp-db"), session.started_at
        )
    except (effect.StateUnavailable, RangeUnavailable):
        return {"achieved": 0, "total": total}

    windows = [case for case in session.cases.filter(malicious=True) if not _replayed(case)]
    rows = []
    for tier, at in effect.credited(spec, session.baseline, changes):
        case = _effect_window(windows, at)
        if case is None:
            continue
        rows.append(Objective(
            session=session, key=tier["key"], name=tier["name"],
            category=tier.get("category") or "", difficulty=int(tier["difficulty"]),
            achieved_at=at,
            earliest=case.started_at - scoreboard.CLOCK_SKEW,
            latest=case.ended_at + scoreboard.CLOCK_SKEW,
        ))
    before = session.objectives.count()
    Objective.objects.bulk_create(rows, ignore_conflicts=True)
    return {"achieved": session.objectives.count() - before, "total": total}


def _effect_window(cases, at):
    inside = [
        case for case in cases
        if case.started_at - scoreboard.CLOCK_SKEW <= at <= case.ended_at + scoreboard.CLOCK_SKEW
    ]
    return max(inside, key=lambda case: case.started_at, default=None)

@require_http_methods(["POST"])
def session_loot(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    _refuse_closed(session)
    if wargames.objective_model(session.scenario) != "loot_verified":
        raise BadRequest(
            f"{session.scenario!r} does not take loot; its objective model is "
            f"{wargames.objective_model(session.scenario)!r}"
        )
    truth = session.baseline
    if not isinstance(truth, dict):
        raise Conflict(
            f"session {session.pk} captured no ground-truth snapshot at start, "
            f"so submitted loot cannot be verified"
        )
    body = _payload(request)
    return _reply(_credit_loot(session, body.get("loot"), body.get("case_id")))

def _credit_loot(session, submitted, case_id):
    truth = session.baseline
    spec = wargames.objectives(session.scenario)
    matched_users = loot.matched(submitted, truth)
    fired, coverage = loot.tiers_fired(spec, matched_users, truth)

    attempted = session.cases.filter(malicious=True).exists()
    credited = fired if attempted else []

    at, earliest, latest = _loot_window(session, case_id, timezone.now())
    attributed = scoreboard.attribute(at, _malicious_attempts(session), earliest, latest)
    _keep_loot(session, matched_users, case_id, attributed)

    before = session.objectives.count()
    Objective.objects.bulk_create(
        [
            Objective(
                session=session, key=tier["key"], name=tier["name"],
                category=tier.get("category") or "", difficulty=int(tier["difficulty"]),
                achieved_at=at, earliest=earliest, latest=latest,
            )
            for tier in credited
        ],
        ignore_conflicts=True,
    )
    return {
        "matched": sorted(matched_users),
        "coverage": coverage,
        "credited": [tier["key"] for tier in credited],
        "objectives": session.objectives.count() - before,
        "attempted": attempted,
        "unattributed": [] if attributed else [tier["key"] for tier in credited],
    }

def _keep_loot(session, matched_users, case_id, attributed):
    owner = session.cases.filter(case_id=case_id, malicious=True).first() if case_id else None
    owner = owner or (session.cases.filter(case_id=attributed.case_id).first() if attributed else None)
    if owner is None or not matched_users:
        return
    owner.meta = dict(owner.meta, loot=sorted(set(owner.meta.get("loot") or []) | matched_users))
    owner.save(update_fields=["meta"])

def _loot_window(session, case_id, submitted_at):
    if case_id:
        case = session.cases.filter(case_id=case_id, malicious=True).first()
        if case is not None:
            return (
                case.ended_at,
                case.started_at - scoreboard.CLOCK_SKEW,
                case.ended_at + scoreboard.CLOCK_SKEW,
            )
    return (
        submitted_at,
        submitted_at - scoreboard.ATTRIBUTION_WINDOW,
        submitted_at + scoreboard.CLOCK_SKEW,
    )

def _malicious_attempts(session):
    return [
        scoreboard.Attempt(
            case_id=case.case_id,
            started_at=case.started_at,
            ended_at=case.ended_at,
            malicious=True,
            detected=False,
            detection_ids=(),
        )
        for case in session.cases.filter(malicious=True)
    ]

@require_http_methods(["POST"])
def fire_attack(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    _refuse_closed(session)
    body = _payload(request)
    try:
        if body.get("lesson") is True:
            recorded, _ = _lesson_fire(session, _lesson_case(session, body.get("case")), {"replay": True})
            return _reply(_shape(recorded, CASE_FIELDS) | {
                "diagnosis": lesson.verdict([_row(session, recorded)])[1][1:],
                "replay": _replay_row(session, recorded),
            }, status=201)
        recorded, _ = _fire(session, body.get("case"), body.get("origin"), _answered)
    except harness.ToolUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)
    return _reply(_shape(recorded, CASE_FIELDS), status=201)

def _fire(session, name, requested_origin=None, witness=lambda ran: {}):
    try:
        case = wargames.find_case(session.scenario, name)
    except wargames.UnknownWargame as exc:
        raise Http404(str(exc))
    case = dict(case, case_id=str(uuid.uuid4()))
    case.setdefault("correlation", "marker")
    adapter = _range(session)
    origin = _origin_for(session, requested_origin)
    if origin:
        attacker.wear_origin(origin, adapter.runner("proxy"))
    launched_on = origin["id"] if origin else settings.RANGE.default_origin

    target_url = origin["target_url"] if origin else settings.TARGET_URL
    spec = dict(case.get("request") or {})
    if spec:
        spec["headers"] = dict(spec.get("headers") or {}, Host=wargames.host(session.scenario))
        case["request"] = spec

    started_at = timezone.now()
    ran = harness.fire(case, adapter.launcher(launched_on), target_url)

    finished_at = timezone.now()
    Session.objects.filter(pk=session.pk, ended_at__lt=finished_at).update(ended_at=finished_at)
    recorded = _record_case(
        session, case, started_at, finished_at,
        dict(
            harness.case_meta(case),
            **({"origin": origin["id"], "target_url": origin["target_url"]}
               if origin else {}),
            **({"source_ip": origin["source_ip"]}
               if origin and settings.ATTACKER_ORIGIN_MODE == "snat" else {}),
            launched_on=launched_on,
            **witness(ran),
        ),
    )
    _settle_and_observe(session)
    return recorded, ran

def _lesson_case(session, name):
    taught = _lesson_of(session) if session.guidance else None
    if not taught:
        raise BadRequest(f"session {session.pk} is not a lesson, so it replays no lesson case")
    if name not in taught["cases"]:
        raise BadRequest(f'"case" must be one of the lesson\'s cases {taught["cases"]}, got {name!r}')
    return name

def _replayed(case):
    return any(case.meta.get(mark) for mark in REPLAY_MARKS)

def _answered(ran):
    status = tools.status(getattr(ran, "output", ""))
    return {"status": status} if status else {}

def _lesson_fire(session, name, marks):
    malicious = wargames.find_case(session.scenario, name)["malicious"]
    truth = session.baseline if isinstance(session.baseline, dict) else {}

    def witness(ran):
        if not malicious:
            status = tools.status(ran.output)
            return dict(marks, status=status, blocked=status == 403)
        leaked = sorted(loot.matched(tools.dumped(ran.output), truth))
        held = not leaked and tools.found_not_injectable(ran.exit_code, ran.output)
        return dict(marks, leaked=leaked, forbidden=tools.forbidden(ran.output), conclusions=tools.conclusions(ran.output),
                    outcome="leaked" if leaked else "held" if held else "inconclusive",
                    blocked=held)

    return _fire(session, name, None, witness)

@require_http_methods(["POST"])
def session_verify(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    _refuse_closed(session)
    taught = _lesson_of(session)
    if not taught:
        raise BadRequest(f"{session.scenario!r} has no lesson to verify")
    if not _verifies(taught):
        raise BadRequest(f"lesson {taught['id']!r} is judged by its steps; it has no VERIFY")
    if not (isinstance(session.baseline, dict) and session.baseline):
        raise Conflict(
            f"session {session.pk} holds no snapshot of the target's accounts, so a "
            f"leak could not be told from a block; open a new session"
        )
    run = str(uuid.uuid4())
    _snapshot_waf(session, run=run)
    try:
        for name in taught["cases"]:
            _lesson_fire(session, name, {"verify": run, "mode": session.mode})
    except harness.ToolUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)
    return _reply(_verified(session, run, watch=True))

def _verifies(taught):
    steps = taught.get("steps") or []
    return not steps or any(step["check"]["kind"] == "verify" for step in steps)

def _row(session, case):
    return {"name": case.name, "malicious": case.malicious,
            "accounts": len(session.baseline) if isinstance(session.baseline, dict) else 0,
            "leaked": case.meta.get("leaked") or [], "status": case.meta.get("status", 0),
            "outcome": case.meta.get("outcome", "inconclusive")}

def _verified(session, run, watch=False):
    ran = list(session.cases.filter(meta__verify=run))
    waf = next((taken["waf"] for taken in session.waf_snapshots if taken.get("run") == run), None)
    judged = _judged_cases(session, ran, watch)
    wanted = (_lesson_of(session) or {}).get("solved_at")
    unsolved = lesson.unsolved(waf, crs.checked(wanted)) if wanted and judged["passed"] else []
    return {
        **judged,
        "passed": judged["passed"] and not unsolved,
        "diagnosis": judged["diagnosis"] + unsolved,
        "run": run,
        "mode": next((case.meta.get("mode") for case in ran if case.meta.get("mode")), None),
        "waf": waf,
        "fix": _fix(session, waf),
    }

def _judged_cases(session, cases, watch=False):
    taught = _lesson_of(session) or {}
    if taught.get("detected_by"):
        rows = _detection_rows(session, taught, cases, watch)
        passed, diagnosis = lesson.detection_verdict(rows)
        return {"passed": passed, "diagnosis": diagnosis, "cases": [
            {"name": row["name"], "malicious": row["malicious"], "outcome": lesson.detection_outcome(row),
             "verdict": lesson.scored(row)} for row in rows]}
    rows = [_row(session, case) for case in cases]
    passed, diagnosis = lesson.verdict(rows)
    return {
        "passed": passed,
        "cases": [
            {"name": row["name"], "malicious": row["malicious"], "outcome": lesson.outcome(row)}
            for row in rows
        ],
        "diagnosis": diagnosis,
    }

def _started(session):
    seeded = list(session.cases.filter(meta__seed=True))
    return _judged_cases(session, seeded) if seeded else None

@require_http_methods(["GET"])
def lesson_debrief(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    taught = _taught(session)
    runs = list(dict.fromkeys(case.meta["verify"] for case in session.cases.all() if case.meta.get("verify")))
    last = _verified(session, runs[-1]) if runs else None
    started = _started(session)
    before = {case["name"]: case["outcome"] for case in (started or {}).get("cases", [])}
    after = {case["name"]: case["outcome"] for case in (last or {}).get("cases", [])}
    steps = {step["id"] for step in taught.get("steps", [])}
    return _reply({
        "lesson": taught["id"],
        "title": f"{taught['text']}.title",
        "overview": {
            "passed": last["passed"] if last else None, "verified": len(runs),
            "mode": last["mode"] if last else session.mode, "fix": last["fix"] if last else None,
            "steps": {"passed": sum(1 for step_id, kept in session.lesson_steps.items()
                                    if step_id in steps and kept.get("passed")), "total": len(steps)},
            "help": lesson.help_counts(session.lesson_steps),
        },
        "evidence": _evidence_rows(session, runs[-1] if runs else None),
        "change": _change(session, (last or {}).get("waf")),
        "cases": [{"name": name, "malicious": wargames.find_case(session.scenario, name)["malicious"],
                   "before": before.get(name), "after": after.get(name)} for name in taught["cases"]],
        "risk": lesson.risks(last["fix"] if last else None,
                             sum(1 for name in taught["cases"] if wargames.find_case(session.scenario, name)["malicious"])),
        "at": {"opened": session.started_at.isoformat(),
               "verified": max((case.ended_at for case in session.cases.filter(meta__verify=runs[-1])),
                               default=None) if runs else None},
    })

EVIDENCE_ROWS = 20

def _evidence_rows(session, run):
    phases = {case.case_id: ("verify" if case.meta.get("verify") == run else "seed", case.name)
              for case in session.cases.all() if case.meta.get("seed") or (run and case.meta.get("verify") == run)}
    found = session.detections.filter(marker__in=list(phases)).order_by("-timestamp")[:EVIDENCE_ROWS]
    return [
        {"id": detection.id, "source": detection.source, "signature": detection.signature,
         "method": _request_of(detection.raw or {})[0], "path": _request_of(detection.raw or {})[1],
         "phase": phases[detection.marker][0], "case": phases[detection.marker][1],
         "timestamp": detection.timestamp.isoformat()}
        for detection in found
    ]

def _change(session, waf):
    declared = (wargames.WARGAMES[session.scenario].get("defense") or {}).get(session.defense)
    before = crs.checked(declared["waf"]) if declared else {"paranoia": None, "exclusions": []}
    if not waf:
        return {"before": before, "after": None, "added": [], "removed": [], "diff": []}
    return {
        "before": before,
        "after": {"paranoia": waf.get("paranoia"), "exclusions": waf.get("exclusions") or []},
        **lesson.exclusions_changed(before["exclusions"], waf.get("exclusions") or []),
        "diff": lesson.config_diff(crs.rendered(before) if before["paranoia"] else "", waf.get("file") or ""),
    }

@require_http_methods(["GET", "PUT"])
def session_waf(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    if request.method == "PUT":
        _refuse_closed(session)
        body = _payload(request)
        crs.checked(body)
        with _turn_of(session):
            standing = _waf_in_force(session)
            tuning = crs.checked({**({} if "thresholds" in body else _thresholds_of(standing)), **body})
            session.waf = crs.apply(tuning, _range(session).runner("gateway"), settings.FSL_WAF)
            session.save(update_fields=["waf"])
        scenario_run.waf_applied(session, tuning, (standing.get("file") or "").strip() == crs.rendered(tuning).strip())
    tuning = _waf_in_force(session)
    return _reply(dict(tuning, version=_version(json.dumps(tuning, sort_keys=True))))

def _thresholds_of(standing):
    return {"thresholds": standing["thresholds"]} if standing.get("thresholds") else {}

def _waf_in_force(session):
    recorded = {"file": None} | (session.waf or {"paranoia": None, "exclusions": []})
    if session.ended_at is not None:
        return recorded
    try:
        return _waf_read(session)
    except RangeUnavailable:
        return recorded

def _waf_read(session):
    gateway = functools.partial(_range(session).runner("gateway"), timeout=CHECK_TIMEOUT)
    return crs.read(gateway, settings.FSL_WAF)

def _snapshot_waf(session, **taken):
    try:
        read = _waf_read(session)
    except (RangeUnavailable, Drifted):
        return None
    snapshot = {"at": timezone.now().isoformat(), **taken, "waf": read}
    with transaction.atomic():
        held = Session.objects.select_for_update().get(pk=session.pk)
        held.waf_snapshots = [*held.waf_snapshots, snapshot]
        held.waf = read
        held.save(update_fields=["waf_snapshots", "waf"])
    session.waf_snapshots, session.waf = held.waf_snapshots, held.waf
    return snapshot

def _record_case(session, case, started_at, ended_at, meta):
    return Case.objects.create(
        session=session,
        case_id=case["case_id"],
        name=case["name"],
        malicious=case["malicious"],
        stage=case.get("stage") or "",
        technique=case.get("technique") or "",
        pattern=case.get("pattern") or "",
        expect=case.get("expect") or "",
        correlation=case["correlation"],
        source_ip=case.get("source_ip"),
        started_at=started_at,
        ended_at=ended_at,
        meta=meta,
    )

def _settle_and_observe(session):
    return _observe_objectives(session)["achieved"]

ROTATE = "rotate"

def _origin_for(session, requested):
    if not requested:
        return None

    described = _standing(session)
    if requested != ROTATE:
        return attacker.find(described, requested)

    available = attacker.origins(described)
    if not available:
        raise attacker.UnknownOrigin("the stack declares no origins to rotate through")
    return available[_take_turn(session) % len(available)]

def _take_turn(session):
    with transaction.atomic():
        Session.objects.filter(pk=session.pk).update(rotation=F("rotation") + 1)
        return Session.objects.values_list("rotation", flat=True).get(pk=session.pk) - 1

@require_http_methods(["GET", "PATCH"])
def session_detail(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    if request.method == "PATCH":
        _refuse_closed(session)
        _taught(session)
        mode = _payload(request).get("mode")
        if mode not in MODES:
            raise BadRequest(f'"mode" must be one of {list(MODES)}, got {mode!r}')
        Session.objects.filter(pk=session.pk).update(mode=mode)
        session.mode = mode
    taught = _lesson_of(session) if session.guidance else None
    if taught:
        hidden = SERVER_ONLY + (SCHEDULE if session.course_scenario else ())
        taught = {key: value for key, value in taught.items() if key not in hidden} | {
            "steps": [_shown_step(session, step) for step in taught.get("steps", [])], "verifies": _verifies(taught),
            **({"cases": []} if session.course_scenario else {})}
    return _reply(_described(session, judged=True) | {
        "lesson": taught, "discover": _discover(session), "waf_terminal": _waf_terminal_url(session),
        "waf_box": f"fsl-{session.pk}-waf", "waf_rules": str(PurePosixPath(settings.FSL_WAF.rules).parent),
        "site": _site(session), "hints": session.hints, "progress": _progress(session),
        "start": _started(session) if taught and taught["verifies"] else None,
    })

def _shown_step(session, step):
    check = step["check"]
    kept = {key: value for key, value in step.items()
            if key not in SERVER_ONLY_STEP and not (key == "command" and session and not _command_shown(session, step))}
    if session and check["kind"] == "kali" and _command_shown(session, step):
        kept["command"] = _command_of(session, step)
    shown = dict(kept, check={"kind": check["kind"], **{key: check[key] for key in SHOWN_CHECK.get(check["kind"], ())}})
    if not step.get("query"):
        return shown
    return dict(shown, discover=_discover(session, step["query"], everything=step.get("records") == "all"))

def _site(session):
    if not settings.SITE_PORT:
        return None
    return {"port": settings.SITE_PORT, "path": f"/site/{session.pk}/{wargames.host(session.scenario)}/"}

def _waf_terminal_url(session):
    if settings.WAF_SESSION_TERMINAL_URL:
        return settings.WAF_SESSION_TERMINAL_URL.format(session=session.pk)
    return settings.WAF_TERMINAL_URL

def _session_index(session):
    return settings.ELASTIC_SESSION_INDEX.format(session=session.pk, slot=_slot_of(session))

def _discover(session, narrowed=None, everything=False):
    return kibana.discover_path(
        _session_index(session),
        session.started_at - timedelta(minutes=1),
        session.ended_at and session.ended_at + timedelta(minutes=1),
        narrowed,
        everything,
    )

@require_http_methods(["POST"])
def close_session(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    _refuse_closed(session)

    adapter = substrate()
    resets = hasattr(adapter, "rebuild_slot") and hasattr(adapter, "configure_slot")
    number = _slot_of(session) if _slotted(adapter) and adapter.slots > 1 else 1
    closed_at = timezone.now()
    with SLOT_CHOICE:
        claimed = resets and reset.claim(number)
        if not Session.objects.filter(pk=session.pk, ended_at=None).update(ended_at=closed_at):
            if claimed:
                reset.release(number)
            session.refresh_from_db()
            _refuse_closed(session)
    session.ended_at = closed_at
    site.forget(session.pk)
    reply = _shape(session, SESSION_FIELDS)

    begun = None
    try:
        scenario_run.end(session)
        if (session.traffic or {}).get("running"):
            customers.stop_on_close(session, _range(session, adapter))
        _snapshot_waf(session, closed=True)
        if hasattr(adapter, "rebuild_slot"):
            begun = _rebuilt_on_close(session, adapter, closed_at, claimed, reply)
    finally:
        if claimed and begun is None:
            reset.release(number)
    return _reply(reply)

def _rebuilt_on_close(session, adapter, closed_at, claimed, reply):
    turn = _turn_of(session, adapter)
    try:
        adapter = _range(session, adapter)
        with turn:
            rebuilt = getattr(adapter, "reset_slot", adapter.rebuild_slot)()
        reply["rebuilding"] = [
            {"host": _named_in(_slot_of(session), host), "server": server}
            for host, server in rebuilt
        ]
    except (Drifted, RangeUnavailable) as exc:
        reply["rebuild"] = str(exc)
        return None
    if not hasattr(adapter, "configure_slot"):
        return None
    _lifted_by_the_rebuild(closed_at, _slot_of(session))
    return claimed and reset.begin(adapter, turn, rebuilt, claimed=True)

def _lifted_by_the_rebuild(rebuilt_at, number=1):
    Suppression.objects.filter(
        _of_slot(number), restored_at__isnull=True, created_at__lte=rebuilt_at,
    ).update(restored_at=rebuilt_at)

@require_http_methods(["GET", "POST"])
def session_cases(request, session_id):
    session = get_object_or_404(Session, pk=session_id)

    if request.method == "GET":
        return _reply([_shape(c, CASE_FIELDS) for c in session.cases.all()])

    _refuse_closed(session)
    body = _payload(request)
    errors = _case_errors(body)
    if errors:
        return _reply(errors, status=400)

    try:
        case = _record_case(
            session, body, _instant(body["started_at"]), _instant(body["ended_at"]),
            body.get("meta") or {},
        )
    except IntegrityError:
        raise Conflict(f"case {body['case_id']} is already recorded in session {session.pk}")
    return _reply(
        _shape(case, CASE_FIELDS) | {"objectives": _settle_and_observe(session)}, status=201
    )

def _instant(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = parse_datetime(value)
    except ValueError:
        return None
    if parsed is None or parsed.tzinfo is None:
        return None
    return parsed

def _case_errors(body):
    errors = {
        field: ["This field is required."]
        for field in CASE_REQUIRED
        if body.get(field) is None
    }
    if body.get("malicious") is not None and not isinstance(body["malicious"], bool):
        errors["malicious"] = [f"must be true or false, got {body['malicious']!r}."]
    if body.get("expect") is not None and not isinstance(body["expect"], str):
        errors["expect"] = [f"must be text or null, got {body['expect']!r}."]
    for field in ("started_at", "ended_at"):
        if body.get(field) is not None and _instant(body[field]) is None:
            errors[field] = [f"must be an ISO 8601 time with its offset, got {body[field]!r}."]
    started, ended = _instant(body.get("started_at")), _instant(body.get("ended_at"))
    if started and ended and ended < started:
        errors["ended_at"] = ["is before started_at."]
    source = body.get("source_ip")
    if source is not None:
        try:
            ipaddress.ip_address(source if isinstance(source, str) else "")
        except ValueError:
            errors["source_ip"] = [f"must be an IP address, got {source!r}."]
    correlation = body.get("correlation")
    if correlation is not None and correlation not in CORRELATION_STRATEGIES:
        errors["correlation"] = [
            f'"{correlation}" is not a valid choice; expected one of '
            f"{', '.join(CORRELATION_STRATEGIES)}."
        ]
    return errors

@require_http_methods(["POST"])
def ingest_detections(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    within = _payload(request).get("within")
    if within is not None and (isinstance(within, bool) or not isinstance(within, int) or within < 1):
        raise BadRequest(f'"within" is a number of seconds above zero, got {within!r}')
    return _reply(_ingest(session, within))

INGEST_PAGES = 40

def _fetched(index, start, end, newest_first):
    documents, truncated = elastic.fetch(settings.ELASTIC_URL, index, start, end, newest_first=newest_first)
    seen = {doc_id for doc_id, _ in documents}
    page = documents
    for _ in range(INGEST_PAGES):
        if newest_first or not truncated or not page:
            break
        after = parse_datetime(str(page[-1][1].get("@timestamp") or ""))
        if after is None or after <= start:
            break
        start = after
        page, more = elastic.fetch(settings.ELASTIC_URL, index, start, end)
        fresh = [(doc_id, doc) for doc_id, doc in page if doc_id not in seen]
        seen.update(doc_id for doc_id, _ in fresh)
        documents = documents + fresh
        truncated = more and (len(documents), max(truncated[1], len(documents)))
        if not fresh:
            break
    return documents, truncated

def _ingest(session, within=None):
    start = session.started_at - timedelta(minutes=1)
    end = (session.ended_at or timezone.now()) + timedelta(minutes=1)
    if within is not None:
        start = max(start, timezone.now() - timedelta(seconds=within))
    try:
        restored = _restore_expired()
    except (RangeUnavailable, suricata.RulesUnreadable):
        restored = []

    documents, truncated = _fetched(_session_index(session) or settings.ELASTIC_INDEX, start, end,
                                    newest_first=within is not None)

    held = dict(session.detections.values_list("detection_id", "marker"))
    known = set(held)
    unmarked = {detection_id for detection_id, marker in held.items() if marker is None}
    stale = 0
    rows = []

    alerts = elastic.normalize_all(documents)
    for alert in alerts:
        if alert["marker"] and alert["detection_id"] in unmarked:
            Detection.objects.filter(
                session=session, detection_id=alert["detection_id"], marker=None
            ).update(marker=alert["marker"])

    productive = {a["detection_id"].split(":")[0] for a in alerts}
    skipped = sum(1 for doc_id, _ in documents if doc_id not in productive)

    _, hosts = _segments(session, recent=True)

    for alert in alerts:
        if alert["detection_id"] in known or alert["timestamp"] is None:
            continue
        known.add(alert["detection_id"])
        if not start <= alert["timestamp"] <= end:
            stale += 1
            continue
        raw = alert.get("raw") or {}
        rows.append(Detection(
            session=session,
            src_host=hosts.get(alert.get("src_ip"), ""),
            dest_host=hosts.get(_request_of(raw)[2], ""),
            **alert,
        ))

    before = session.detections.count()
    Detection.objects.bulk_create(rows, ignore_conflicts=True)
    ingested = session.detections.count() - before

    reply = {"ingested": ingested, "skipped": skipped, "stale": stale, "restored": restored}
    if truncated and within is None:
        read, total = truncated
        reply["truncated"] = {"read": read, "total": total}
        session.read_of = [read, total]
        session.save(update_fields=["read_of"])
    return reply

@require_http_methods(["GET"])
def session_detections(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    detections = session.detections.all()

    after = request.GET.get("after")
    if after is not None:
        try:
            detections = detections.filter(id__gt=int(after, 10))
        except ValueError:
            raise BadRequest(f'"after" must be a row id, got {after!r}')

    detections = list(detections)
    addresses = {d.src_ip for d in detections if d.src_ip}
    zones, _ = _segments(session, recent=True) if addresses else ([], {})
    located = _located(session.detections.filter(src_ip__in=addresses)) if addresses else {}
    return _reply([_listed(session, d, zones, located) for d in detections])

@require_http_methods(["GET"])
def detection_detail(request, detection_id):
    detection = get_object_or_404(Detection, pk=detection_id)
    shown = _shape(detection, DETECTION_DETAIL_FIELDS) | {"session": detection.session_id}
    return _reply(json.loads(site.shown_marker(detection.session, json.dumps(shown, default=str))))

@require_http_methods(["GET"])
def session_map(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    detections = list(session.detections.all())
    site = settings.RANGE.defended_site

    located = {}
    for detection in detections:
        if not detection.src_ip or detection.src_ip in located:
            continue
        geo = (detection.raw or {}).get("src_geo") or {}
        where = geo.get("location") or {}
        if where.get("lat") is None or where.get("lon") is None:
            continue
        located[detection.src_ip] = (where["lat"], where["lon"], geo)

    points, unlocated = {}, 0
    for detection in detections:
        place = located.get(detection.src_ip)
        if place is None:
            unlocated += 1
            continue
        lat, lon, geo = place
        point = points.setdefault(
            (lat, lon),
            {
                "lat": lat,
                "lon": lon,
                "country": geo.get("country_name") or "",
                "country_code": geo.get("country_iso_code") or "",
                "city": geo.get("city_name") or "",
                "detections": 0,
                "ips": [],
            },
        )
        point["detections"] += 1
        if detection.src_ip not in point["ips"]:
            point["ips"].append(detection.src_ip)

    return _reply(
        {
            "points": sorted(points.values(), key=lambda p: -p["detections"]),
            "unlocated": unlocated,
            "target": site and _shape(site, ("lat", "lon", "label")),
        }
    )

@require_http_methods(["GET"])
def session_score(request, session_id):
    session = get_object_or_404(Session, pk=session_id)

    forced = request.GET.get("correlation")
    if forced is not None and forced not in CORRELATION_STRATEGIES:
        raise BadRequest(
            f'"{forced}" is not a valid strategy; expected one of '
            f"{', '.join(CORRELATION_STRATEGIES)}."
        )

    cases, detections, result, signatures = _evidence(session, forced)
    if (session.traffic or {}).get("running"):
        customers.refresh(session, _range(session))
    alerted = customers.alerted_markers(session)
    unmatched = set(result.unmatched_detection_ids)
    totals = compute_score(result)
    per_case = _per_case(result, _expected(session.scenario, cases), signatures)
    breaches = _breaches(session, cases, result)
    board = scoreboard.tally(breaches, totals.fp)
    warnings = list(totals.warnings) + _wrong_reason_warnings(per_case)
    if session.read_of:
        read, total = session.read_of or [0, 0]
        warnings.append(("score.warning.truncated", read, total))

    return _reply(
        {
            **_shape(totals, SCORE_FIELDS),
            "benign_cases": totals.fp + totals.tn,
            "unattributed": sum(1 for d in detections if d.detection_id in unmatched and d.marker not in alerted),
            "customers": customers.availability(session, alerted),
            "warnings": warnings,
            "per_case": per_case,
            "objectives": board.__dict__,
            "breaches": [
                dict(b.__dict__, detection_ids=list(b.detection_ids)) for b in breaches
            ],
            "game": _game(session, cases, detections, result, breaches, totals),
        }
    )

@require_http_methods(["GET", "PUT", "DELETE"])
def session_traffic(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    try:
        if request.method == "GET":
            customers.refresh(session, _range(session))
        elif request.method == "DELETE":
            customers.stop(session, _range(session))
        else:
            _refuse_closed(session)
            customers.start(session, _range(session), _payload(request))
    except customers.NoTraffic as exc:
        raise Http404(str(exc))
    except traffic.InvalidTraffic:
        raise
    except ValueError as exc:
        raise BadRequest(str(exc))
    except (traffic.NoOrigin, RangeUnavailable) as exc:
        return _reply({"detail": str(exc)}, status=503)
    return _reply(customers.status(session))

def _evidence(session, forced=None):
    replayed = {case.case_id for case in session.cases.all() if _replayed(case)}
    cases = [case for case in session.cases.all() if case.case_id not in replayed]
    detections = [
        d for d in session.detections.all() if d.marker not in replayed and d.marker != session.browse_marker
    ]
    records = [c.to_record() for c in cases]
    if forced:
        records = [replace(record, correlation=forced) for record in records]
    result = correlate(records, [d.to_record() for d in detections])
    return cases, detections, result, {d.detection_id: d.signature for d in detections}

def _game(session, cases, detections, result, breaches, totals):
    if session.ended_at is None:
        return {"revealed": False}

    detected_at = {d.detection_id: d.timestamp for d in detections}
    first_hit = {
        match.case_id: min(
            (detected_at[d] for d in match.detection_ids if d in detected_at),
            default=None,
        )
        for match in result.matches
    }
    attempts = [
        game.Attempt(
            case_id=case.case_id,
            malicious=case.malicious,
            stage=case.stage or "",
            started_at=case.started_at,
            detected_at=first_hit.get(case.case_id),
            blocked=bool(case.meta.get("blocked")),
        )
        for case in cases
    ]
    taken = [
        game.Taken(key=b.key, difficulty=b.difficulty, detected=b.detected)
        for b in breaches
    ]
    settled = game.settle(attempts, taken, totals.tp, totals.fp, totals.fn, totals.tn)
    return dict(settled.__dict__, revealed=True)

def _attempts(cases, result):
    by_case = {match.case_id: match for match in result.matches}
    return [
        scoreboard.Attempt(
            case_id=case.case_id,
            started_at=case.started_at,
            ended_at=case.ended_at,
            malicious=case.malicious,
            detected=bool(by_case[case.case_id].detected),
            detection_ids=tuple(by_case[case.case_id].detection_ids),
        )
        for case in cases
        if case.case_id in by_case
    ]

def _breaches(session, cases, result):
    attempts = _attempts(cases, result)
    breaches = []
    for objective in session.objectives.all():
        credited = scoreboard.attribute(
            objective.achieved_at, attempts, objective.earliest, objective.latest
        )
        breaches.append(
            scoreboard.Breach(
                key=objective.key,
                name=objective.name,
                category=objective.category,
                difficulty=objective.difficulty,
                detected=bool(credited and credited.detected),
                detection_ids=tuple(credited.detection_ids) if credited else (),
            )
        )
    return breaches

def _expected(scenario, cases):
    catalogue = {}
    if any(case.expect is None for case in cases):
        try:
            catalogue = wargames.expectations(scenario)
        except wargames.UnknownWargame:
            pass
    return {
        case.case_id: catalogue.get(case.name) if case.expect is None else case.expect
        for case in cases
    }

def _per_case(result, expectations, signatures):
    indiscriminate = {
        signatures[d]
        for m in result.matches if not m.malicious
        for d in m.detection_ids if d in signatures
    }
    return [
        {
            "case_id": m.case_id,
            "name": m.name,
            "malicious": m.malicious,
            "detected": m.detected,
            "verdict": _verdict(m.malicious, m.detected),
            "detection_ids": list(m.detection_ids),
            "expect": expectations.get(m.case_id) or "",
            "corroborated": scoreboard.corroborated(
                expectations.get(m.case_id),
                [signatures[d] for d in m.detection_ids if d in signatures],
                indiscriminate,
            ),
        }
        for m in result.matches
    ]

def _wrong_reason_warnings(per_case):
    wrong = [c["name"] for c in per_case if c["detected"] and c["corroborated"] is False]
    if not wrong:
        return []
    return [("score.warning.wrong_reason", ", ".join(wrong))]

def _verdict(malicious: bool, detected: bool) -> str:
    if malicious:
        return "TP" if detected else "FN"
    return "FP" if detected else "TN"

@require_http_methods(["GET"])
def current_rules(request):
    content = _live_rules(_asked_session(request))
    return _reply({"content": content, "version": _version(content)})

@require_http_methods(["POST"])
def validate_rules(request):
    content = _rule_file(request)
    session = _asked_session(request)
    with _turn_of(session):
        outcomes = [suricata.validate(content, runner)
                    for runner, _, _ in _sensors(_range(session))]
    failed = [o for o in outcomes if not o.ok]
    outcome = max(failed, key=lambda o: len(_rule_errors(o.output)), default=outcomes[0])
    errors = list(dict.fromkeys(line for o in failed for line in _rule_errors(o.output)))
    payload = {"ok": outcome.ok, "output": outcome.output.strip(), "errors": errors}
    return _reply(payload, status=200 if outcome.ok else 400)

def _rule_errors(output):
    return [line.strip() for line in output.splitlines() if RULE_ERROR.search(line)]

def _minutes(given) -> float:
    try:
        minutes = float(given)
    except (TypeError, ValueError, OverflowError):
        minutes = math.nan
    if not 0 < minutes <= SUPPRESSION_LONGEST:
        raise BadRequest(
            f'"minutes" must be more than 0 and at most {SUPPRESSION_LONGEST}, '
            f"got {given!r}"
        )
    return minutes

@require_http_methods(["GET", "POST"])
def suppressions(request):
    expired = _restore_expired()

    if request.method == "GET":
        return _reply(
            {
                "suppressions": [
                    _shape(s, SUPPRESSION_FIELDS)
                    for s in Suppression.objects.filter(restored_at__isnull=True)
                ],
                "restored": expired,
            }
        )

    body = _payload(request)
    try:
        sid = int(body.get("sid"))
    except (TypeError, ValueError, OverflowError):
        raise BadRequest(f'"sid" must be a rule id, got {body.get("sid")!r}')

    minutes = _minutes(body.get("minutes", SUPPRESSION_MINUTES))
    expires_at = timezone.now() + timedelta(minutes=minutes)
    session = _written(request)
    with _turn_of(session):
        content = _live_rules(session)

        try:
            silenced = suppress.silence(content, sid, expires_at.isoformat())
        except KeyError:
            raise Http404(f"no active rule carries sid {sid}")

        original = suppress.find(content, sid)
        _apply(silenced, session)

        record = Suppression.objects.create(
            session=session,
            sid=sid,
            original=original,
            reason=body.get("reason") or "",
            expires_at=expires_at,
        )
    return _reply(_shape(record, SUPPRESSION_FIELDS), status=201)

@require_http_methods(["POST"])
def restore_suppression(request, suppression_id):
    record = get_object_or_404(Suppression, pk=suppression_id)
    with _turn_of(record.session):
        record.refresh_from_db()
        return _restored(record)

def _restored(record):
    if record.restored_at is not None:
        return _reply(_shape(record, SUPPRESSION_FIELDS) | {
            "detail": f"sid {record.sid} was already restored at {record.restored_at.isoformat()}"
        })
    ok, detail = _restore(record)
    if not ok:
        return _reply({"detail": detail}, status=400)
    return _reply(_shape(record, SUPPRESSION_FIELDS) | {"detail": detail})

def _restore(record) -> tuple[bool, str | None]:
    try:
        current = _live_rules(record.session)
    except RangeUnavailable:
        if record.session is None or record.session.ended_at is None:
            raise
        adapter = _range(record.session)
        rebuilt = hasattr(adapter, "rebuild_slot")
        if not rebuilt and (not hasattr(adapter, "has_stack") or adapter.has_stack()):
            raise
        record.restored_at = timezone.now()
        record.save(update_fields=["restored_at"])
        return True, (
            f"session {record.session_id} has ended and its sensor is "
            f"{'rebuilt from its image' if rebuilt else 'gone'}, so nothing is left silenced"
        )
    superseded = suppress.find(current, record.sid) is not None
    lift = suppress.discard if superseded else suppress.restore
    try:
        content = lift(current, record.sid, record.original)
    except KeyError:
        content = superseded = None
    if content is not None:
        try:
            _apply(content, record.session)
        except suricata.RuleApplyError as exc:
            return False, f"could not restore sid {record.sid}: {exc}"

    record.restored_at = timezone.now()
    record.save(update_fields=["restored_at"])
    if superseded:
        return True, (
            f"sid {record.sid} was superseded by an active rule carrying it, so "
            f"the silenced original was dropped rather than restored"
        )
    return True, None

def _due():
    return Suppression.objects.filter(
        restored_at__isnull=True, expires_at__lte=timezone.now()
    )

def _restore_expired() -> list:
    if not _due().exists():
        return []
    lifted = []
    for record in list(_due()):
        with _turn_of(record.session):
            record.refresh_from_db()
            if record.restored_at is not None:
                continue
            ok, detail = _restore(record)
        lifted.append({"sid": record.sid, "ok": ok, "detail": detail})
    return lifted

def _sensors(adapter):
    return [
        (adapter.runner(role), reload_command, path)
        for role, path, reload_command in (
            ("sensor", settings.FSL_SENSOR_RULES, settings.FSL_SENSOR_RELOAD),
            *settings.FSL_EXTRA_SENSORS,
        )
    ]

def _live_rules(session=None):
    return suricata.current(_range(session).runner("sensor"), settings.FSL_SENSOR_RULES)

def _apply(content, session=None):
    sensors = _sensors(_range(session))
    previous = suricata.current(sensors[0][0], sensors[0][2]) if len(sensors) > 1 else None
    for done, (runner, reload_command, path) in enumerate(sensors):
        try:
            suricata.apply(content, runner, reload_command, path)
        except suricata.RuleApplyError:
            for undone, undone_reload, undone_path in sensors[:done]:
                suricata.seed(previous, undone, undone_reload, undone_path)
            raise

def _version(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]

@require_http_methods(["POST"])
def apply_rules(request):
    content = _rule_file(request)
    body = _payload(request)
    session = _written(request)
    with _turn_of(session):
        if "base" in body:
            base = body["base"]
            live = _version(_live_rules(session))
            if base != live:
                raise Conflict(
                    "the sensor's rules changed since this copy was loaded "
                    f"(loaded {base or 'nothing'}, live {live}); reload them and edit again"
                )
        _apply(content, session)
    ruleset = RuleSet.objects.create(content=content, applied_at=timezone.now())
    return _reply(_shape(ruleset, RULESET_FIELDS))

def _fabric_plan(plan):
    return {
        "networks": list(plan.networks),
        "subnets": [
            {"segment": s.segment, "name": s.name, "cidr": s.cidr,
             "dhcp": s.dhcp, "gateway": s.gateway}
            for s in plan.subnets
        ],
        "keypair": plan.keypair,
        "groups": list(plan.groups),
        "reach": plan.reach,
        "present": list(plan.present),
        "drifted": list(plan.drifted),
        "leftovers": list(plan.leftovers),
        "clean": plan.clean,
    }

def _built_by_the_cloud(adapter, plans: str, what: str):
    if not hasattr(adapter, plans):
        raise Conflict(
            f"compose builds this range; the {what} built through the "
            f"OpenStack API only"
        )
    return adapter

def _image_plan(plan):
    return {
        "images": [
            {"host": i.host, "bundle": i.bundle, "state": i.state,
             "image": i.image, "builder": i.builder, "detail": i.detail}
            for i in plan.images
        ],
        "leftovers": [
            {"kind": kind, "id": ident, "why": why} for kind, ident, why in plan.leftovers
        ],
        "clean": plan.clean,
    }

@require_http_methods(["GET", "POST", "DELETE"])
def range_images(request):
    adapter = _built_by_the_cloud(substrate(), "plan_images", "images are")
    if request.method == "GET":
        return _reply(_image_plan(adapter.plan_images()))
    with RULE_CHANGES:
        if request.method == "POST":
            return _reply(_image_plan(adapter.ensure_images()))
        removed = adapter.clean_images()
    return _reply({"removed": [{"kind": kind, "id": ident} for kind, ident in removed]})

def _slot_plan(plan):
    number = getattr(plan, "slot", 1)
    named = functools.partial(_named_in, number)
    return {
        "slot": number,
        "boot": [named(host) for host in plan.boot],
        "ports": [
            {"host": named(p.host), "segment": p.segment, "name": p.name,
             "addresses": [address for _, address in p.fixed_ips]}
            for p in plan.ports
        ],
        "standing": [
            {"host": named(host), "server": server, "status": status}
            for host, server, status in plan.standing
        ],
        "blocked": [reason if number == 1 else f"slot {number}: {reason}" for reason in plan.blocked],
        "clean": plan.clean,
    }

def _slot_plans(plans):
    each = [_slot_plan(plan) for plan in plans]
    if len(each) == 1:
        return each[0]
    return {
        **{key: [entry for plan in each for entry in plan[key]]
           for key in ("boot", "ports", "standing", "blocked")},
        "clean": all(plan["clean"] for plan in each),
        "slots": each,
    }

def _asked_slots(request, adapter) -> list[int]:
    given = request.GET.get("slot")
    every = list(range(1, getattr(adapter, "slots", 1) + 1))
    if given in (None, ""):
        return every
    try:
        wanted = int(given)
    except ValueError:
        raise BadRequest(f'"slot" must be a slot number, got {given!r}')
    if wanted not in every:
        raise BadRequest(f"slot {wanted} is not one of the slots {every} the cloud settings ask for")
    return [wanted]

def _each_slot(request, adapter, step):
    numbers = _asked_slots(request, adapter)

    def in_turn(number):
        with _turn(number if _slotted(adapter) else None):
            return step(_in_slot(adapter, number))

    if len(numbers) == 1:
        return [in_turn(numbers[0])]
    with ThreadPoolExecutor(max_workers=len(numbers), thread_name_prefix="fsl-slot") as pool:
        return list(pool.map(in_turn, numbers))

@require_http_methods(["GET", "POST", "DELETE"])
def range_slot(request):
    adapter = _built_by_the_cloud(substrate(), "plan_slot", "slot is")
    if request.method == "GET":
        numbers = _asked_slots(request, adapter)
        if hasattr(adapter, "plan_slots") and len(numbers) > 1:
            return _reply(_slot_plans(adapter.plan_slots()))
        return _reply(_slot_plans([_in_slot(adapter, n).plan_slot() for n in numbers]))
    if request.method == "POST":
        return _reply(_slot_plans(_each_slot(request, adapter, lambda one: one.ensure_slot())))
    removed = [step for steps in _each_slot(request, adapter, lambda one: one.teardown_slot())
               for step in steps]
    return _reply({"removed": [{"kind": kind, "id": ident} for kind, ident in removed]})

@require_http_methods(["POST"])
def range_rebuild(request):
    adapter = _built_by_the_cloud(substrate(), "rebuild_slot", "slot is")
    rebuilt = [pair for pairs in _each_slot(request, adapter, lambda one: _renamed(one, one.rebuild_slot()))
               for pair in pairs]
    return _reply({"rebuilt": [{"host": host, "server": server} for host, server in rebuilt]})

@require_http_methods(["POST"])
def range_configure(request):
    adapter = _built_by_the_cloud(substrate(), "configure_slot", "slot is")

    def configured(one):
        done = one.configure_slot()
        reset.configured_by_hand(getattr(one, "slot", 1))
        return _renamed(one, done)

    done = [pair for pairs in _each_slot(request, adapter, configured) for pair in pairs]
    return _reply({"configured": [
        {"host": host, "reported": list(reported)} for host, reported in done
    ]})

@require_http_methods(["GET"])
def range_console(request, host):
    adapter = _built_by_the_cloud(substrate(), "console", "a console is")
    return _reply({"url": adapter.console(host)})

def _ground_truth_readable(adapter) -> bool:
    try:
        _ground_truth(adapter, "board")
        return True
    except loot.GroundTruthUnavailable:
        return False

def _baseline_rules() -> str:
    return (Path(settings.FSL_SOURCE) / "deploy/suricata/rules/local.rules").read_text()

def _rules_at_baseline(adapter) -> bool:
    try:
        live = [suricata.current(runner, path) for runner, _, path in _sensors(adapter)]
    except (suricata.RulesUnreadable, RangeUnavailable):
        return False
    if any(rules != _baseline_rules() for rules in live):
        return False
    now = timezone.now()
    return not Suppression.objects.filter(
        _of_slot(getattr(adapter, "slot", 1)), restored_at__isnull=True, expires_at__gt=now
    ).exists()

def _holders() -> dict[int, int]:
    return {slot or 1: pk for slot, pk in
            Session.objects.filter(ended_at=None).order_by("pk").values_list("slot", "pk")}

def _readiness(adapter, first_ready=False) -> dict:
    held = _holders()
    numbers = range(1, getattr(adapter, "slots", 1) + 1)
    plans = adapter.plan_slots() if hasattr(adapter, "plan_slots") else [adapter.plan_slot()]
    verdicts = []
    for number, plan in zip(numbers, plans):
        verdicts.append(_range_ready(_in_slot(adapter, number), plan, held.get(number)))
        if first_ready and verdicts[-1]["ready"]:
            return verdicts[-1] | {"slots": [verdict["slot"] for verdict in verdicts]}
    free = [verdict for verdict in verdicts if verdict["slot"].get("session") is None]
    chosen = (next((verdict for verdict in free if verdict["ready"]), None)
              or next((verdict for verdict in free if verdict["slot"].get("phase") in SETTLING_PHASES), None)
              or (free or verdicts)[0])
    return chosen | {"slots": [verdict["slot"] for verdict in verdicts]}

def _range_ready(adapter, plan=None, held=None) -> dict:
    number = getattr(adapter, "slot", 1)
    plan = plan or adapter.plan_slot()
    resetting = reset.standing(number)
    unchecked = resetting["state"] == reset.RUNNING or held is not None
    checks = {
        "active": plan.active,
        "ground_truth": None if unchecked else _ground_truth_readable(adapter),
        "rules_baseline": None if unchecked else _rules_at_baseline(adapter),
    }
    blocked = []
    if held is not None:
        phase = "IN_USE"
        blocked.append(f"session {held} holds this slot")
    elif unchecked:
        phase = "RESETTING"
        blocked.append(
            "the range is resetting after the last session closed (each VM "
            "rebuilt or reset in place, then configured); wait for it, no need to call configure"
        )
    elif resetting["state"] == reset.FAILED:
        phase = "RESET_FAILED"
        blocked.append(
            f"the range reset after the last session failed: {resetting['reason']}; "
            f"POST /api/range/configure/ retries it"
        )
    elif plan.boot or plan.blocked:
        phase = "NOT_STANDING"
        blocked += list(plan.blocked) or [f"{host} is not standing" for host in plan.boot]
    elif not plan.active:
        phase = "REBUILDING"
        blocked += [f"{host} is {status}" for host, _, status in plan.standing
                    if status != "ACTIVE"]
    elif not (checks["ground_truth"] and checks["rules_baseline"]):
        phase = "CHECKING"
    else:
        phase = "READY"
    if checks["ground_truth"] is False:
        blocked.append("the target's ground truth could not be read")
    if checks["rules_baseline"] is False:
        blocked.append("the sensor rules are off baseline or a suppression is in force")
    if number != 1:
        blocked = [f"slot {number}: {reason}" for reason in blocked]
    return {
        "ready": held is None and all(checks.values()) and resetting["state"] == reset.IDLE,
        "substrate": "openstack",
        "slot": {
            "number": number,
            "session": held,
            "phase": phase,
            "reset": resetting,
            "standing": [{"host": host, "server": server, "status": status}
                         for host, server, status in plan.standing],
            "checks": checks,
            "blocked": blocked,
        },
    }

@require_http_methods(["GET"])
def range_ready(request):
    adapter = substrate()
    if not hasattr(adapter, "plan_slot"):
        return _reply({"ready": True, "substrate": "compose", "slot": None,
                       "max_sessions": getattr(adapter, "max_sessions", 1)})
    return _reply(_readiness(adapter) | {"max_sessions": getattr(adapter, "max_sessions", 1)})

CANARY_CASE = {
    "name": "range-canary",
    "malicious": True,
    "correlation": "marker",
    "request": {
        "method": "GET",
        "path": "/search/",
        "params": {"q": "' OR 1=1--"},
    },
}

def _canary_blocked(reason: str) -> dict:
    return {"corroborated": False, "suricata": False, "modsecurity": False,
            "skew_seconds": None, "blocked": [reason]}

def _range_canary(adapter, session=None) -> dict:
    token = "canary-" + uuid.uuid4().hex
    try:
        origin = attacker.find(_standing(session), None)
    except (attacker.UnknownOrigin, RangeUnavailable) as exc:
        return _canary_blocked(f"no origin to fire the canary from: {exc}")
    try:
        attacker.wear_origin(origin, adapter.runner("proxy"))
    except RangeUnavailable as exc:
        return _canary_blocked(f"could not set the canary origin: {exc}")

    case = dict(CANARY_CASE, case_id=token)
    fired_at = timezone.now()
    try:
        harness.fire(case, adapter.launcher(origin["id"]), origin["target_url"])
    except harness.ToolUnavailable as exc:
        return _canary_blocked(f"the canary did not fire: {exc}")

    suricata_at = modsec_at = None
    reach = []
    for _ in range(max(1, int(settings.CANARY_WAIT / settings.CANARY_POLL))):
        time.sleep(settings.CANARY_POLL)
        try:
            documents, _ = elastic.fetch(
                settings.ELASTIC_URL, settings.ELASTIC_INDEX,
                fired_at - timedelta(minutes=1), timezone.now() + timedelta(minutes=1),
            )
        except elastic.ElasticUnavailable as exc:
            reach = [f"could not read Elasticsearch: {exc}"]
            continue
        reach = []
        marked = [d for d in elastic.normalize_all(documents)
                  if d["marker"] == token and d["timestamp"]]
        suricata_at = min((d["timestamp"] for d in marked if d["source"] == "suricata"),
                          default=None)
        modsec_at = min((d["timestamp"] for d in marked if d["source"] == "modsecurity"),
                        default=None)
        if suricata_at and modsec_at:
            break

    skew = (abs((suricata_at - modsec_at).total_seconds())
            if suricata_at and modsec_at else None)
    blocked = list(reach)
    if suricata_at is None:
        blocked.append("Suricata did not alert on the canary")
    if modsec_at is None:
        blocked.append("ModSecurity did not alert on the canary")
    if skew is not None and skew > settings.READY_SKEW:
        blocked.append(
            f"the engine clocks differ by {skew:.1f}s, over the {settings.READY_SKEW:g}s bound"
        )
    return {
        "corroborated": (suricata_at is not None and modsec_at is not None
                         and skew is not None and skew <= settings.READY_SKEW),
        "suricata": suricata_at is not None,
        "modsecurity": modsec_at is not None,
        "skew_seconds": skew,
        "blocked": blocked,
    }

@require_http_methods(["POST"])
def range_canary(request):
    session = _written(request)
    return _reply(_range_canary(_range(session), session))

@require_http_methods(["GET", "POST", "DELETE"])
def range_fabric(request):
    adapter = _built_by_the_cloud(substrate(), "plan_fabric", "fabric is")
    if request.method == "GET":
        return _reply(_fabric_plan(adapter.plan_fabric()))
    with RULE_CHANGES:
        if request.method == "POST":
            return _reply(_fabric_plan(adapter.ensure_fabric()))
        removed = adapter.teardown_fabric()
    return _reply({"removed": [{"kind": kind, "id": ident} for kind, ident in removed]})
