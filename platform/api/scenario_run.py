import copy
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import BadRequest
from django.db import close_old_connections, transaction
from django.db.models import Count, Max, Min
from django.db.models.fields.json import KT
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods

import lesson
import scenarios
import scoreboard
import wargames
from api import customers, views
from api.models import Detection, Session
from api.refusals import Conflict
from ingest import elastic
from range.ports import Drifted, RangeUnavailable
from redteam import tools
from rules import crs

log = logging.getLogger(__name__)

STATE = threading.RLock()
FIRING = ThreadPoolExecutor(max_workers=4, thread_name_prefix="fsl-scenario-attack")
ASKED_KEYS = ("lesson", "guidance", "defense", "mode")
RECENT = 180
MINUTE = timedelta(minutes=1)
SHOWN_ITEMS = 200
SHOWN_RULES = 12
CRS_TOTALS = ("949", "959")
_loop = None
_observed: dict[int, float] = {}
_waf_read: dict[int, float] = {}

def declared_of(session) -> dict:
    return wargames.scenario_run(session.course_scenario)

def settings_for(scenario_id: str, body: dict) -> tuple:
    asked = [key for key in ASKED_KEYS if key in body]
    if asked:
        raise BadRequest(f"scenario {scenario_id} sets its own {', '.join(asked)}; leave them out")
    declared = wargames.scenario_run(scenario_id)
    wargame = wargames.scenario_owner(scenario_id)
    guided = declared.get("steps") is not None
    return wargame, guided, scenario_id if guided else "", declared["defense"], \
        wargames.defense(wargame, declared["defense"])

def begin(session, adapter, posture) -> None:
    declared = declared_of(session)
    opened = timezone.now()
    written = [{"at": opened.isoformat(), "version": scenarios.version_of(crs.rendered(crs.checked(posture["waf"])))}] \
        if posture else []
    session.scenario_state = {
        "id": declared["id"], "opened_at": opened.isoformat(),
        "ends_at": scenarios.ends_at(declared, opened).isoformat(),
        "window_at": scenarios.scheduled_window(declared, opened).isoformat(),
        "schedule": scenarios.schedule(declared, opened), "windows": [], "triage": {}, "offer": None,
        "stuck": [], "waf": written, "last_change": opened.isoformat(), "hints": [],
    }
    session.save(update_fields=["scenario_state"])
    customers.start(session, adapter, dict(declared["traffic"]))
    ensure_running()

def _update(pk, change):
    with STATE, transaction.atomic():
        held = Session.objects.select_for_update().get(pk=pk)
        state = copy.deepcopy(held.scenario_state or {})
        result = change(state, held)
        held.scenario_state = state
        held.save(update_fields=["scenario_state", "hints"])
    return held, result

def ensure_running() -> None:
    global _loop
    with STATE:
        if _loop is not None and _loop.is_alive():
            return
        _loop = threading.Thread(target=_run, name="fsl-scenarios", daemon=True)
        _loop.start()

def resume() -> None:
    def again(state, held):
        for entry in state.get("schedule") or []:
            if entry["state"] == scenarios.FIRING:
                entry["state"] = scenarios.DUE
    for pk in _running().values_list("pk", flat=True):
        _update(pk, again)
    ensure_running()

def _running():
    return Session.objects.filter(ended_at=None).exclude(course_scenario="")

def _run() -> None:
    while True:
        try:
            tick()
        except Exception:
            log.exception("the scenario engine's tick failed")
        finally:
            close_old_connections()
        time.sleep(settings.SCENARIO_TICK)

def tick(now=None) -> None:
    for session in _running():
        if session.scenario_state:
            _advance(session, now or timezone.now())

def _advance(session, now) -> None:
    state = session.scenario_state
    if not state["windows"] and now >= scenarios.at(state["window_at"]):
        session, _ = start_window(session, "schedule", now)
    for entry in scenarios.due_now(session.scenario_state["schedule"], now):
        if _claim(session.pk, entry["n"]):
            _submit(session.pk, entry["n"])
    if time.monotonic() - _observed.get(session.pk, float("-inf")) >= settings.SCENARIO_OBSERVE:
        _observed[session.pk] = time.monotonic()
        _observe(session, now)
    session.refresh_from_db(fields=["scenario_state"])
    window = (session.scenario_state["windows"] or [None])[-1]
    if window and window.get("result") is None and scenarios.ready_to_judge(session.scenario_state["schedule"], window, now):
        judge_window(session)

def _claim(pk, n) -> bool:
    def claim(state, held):
        entry = state["schedule"][n]
        if entry["state"] != scenarios.DUE:
            return False
        entry["state"] = scenarios.FIRING
        return True
    return _update(pk, claim)[1]

def _submit(pk, n) -> None:
    FIRING.submit(fire_entry, pk, n)

def fire_entry(pk, n) -> None:
    try:
        session = Session.objects.get(pk=pk)
        entry = session.scenario_state["schedule"][n]
        if session.ended_at is not None:
            _settle(pk, n, state=scenarios.CANCELLED)
            return
        recorded, _ = views._fire(session, entry["case"], entry["origin"] or None,
                                  lambda ran: _witness(session, n, ran))
        _settle(pk, n, state=scenarios.FIRED, case_id=recorded.case_id, fired_at=recorded.started_at.isoformat(),
                finished_at=recorded.ended_at.isoformat(), **_credited(session, recorded))
    except Exception as exc:
        log.exception("scheduled attack %s of session %s failed", n, pk)
        _settle(pk, n, state=scenarios.FAILED, error=str(exc)[:500] or type(exc).__name__)

def _witness(session, n, ran) -> dict:
    output = getattr(ran, "output", "")
    status = tools.status(output)
    return {"scheduled": session.course_scenario, "entry": n, "dumped": tools.dumped(output),
            "conclusions": tools.conclusions(output), "forbidden": tools.forbidden(output),
            "blocked": status == 403 or tools.found_not_injectable(ran.exit_code, output),
            **({"status": status} if status else {})}

def _credited(session, recorded) -> dict:
    model = wargames.objective_model(session.scenario)
    dumped = recorded.meta.get("dumped") or []
    if model == "loot_verified" and dumped and isinstance(session.baseline, dict) and session.baseline:
        views._credit_loot(session, dumped, recorded.case_id)
        recorded.refresh_from_db()
    leaked = sorted(recorded.meta.get("loot") or [])
    if model == "effect_observed":
        leaked += sorted(session.objectives.filter(
            achieved_at__gte=recorded.started_at - scoreboard.CLOCK_SKEW,
            achieved_at__lte=recorded.ended_at + scoreboard.CLOCK_SKEW).values_list("key", flat=True))
    return {"outcome": scenarios.LEAKED if leaked else scenarios.HELD, "leaked": leaked}

def _settle(pk, n, **changed) -> None:
    def settle(state, held):
        state["schedule"][n].update(changed)
    _update(pk, settle)

def start_window(session, by, now=None):
    now = now or timezone.now()
    declared = declared_of(session)

    def start(state, held):
        windows = state["windows"]
        if windows and windows[-1].get("result") is None:
            raise Conflict(f"session {held.pk}'s verification window is already open until {windows[-1]['ends_at']}")
        end = now + timedelta(minutes=declared["window_minutes"])
        windows.append({"n": len(windows), "started_at": now.isoformat(), "ends_at": end.isoformat(), "by": by,
                        "result": None})
        state["schedule"] += scenarios.window_attacks(declared, state["schedule"], now,
                                                      scenarios.at(state["opened_at"]))
        return windows[-1]
    return _update(session.pk, start)

def _blocked_between(session, start, end) -> int:
    return customers.counted(session.customer_requests.filter(sent_at__gte=start, sent_at__lt=end))["blocked"]

def judge_window(session) -> dict:
    try:
        customers.refresh(session, views._range(session))
    except RangeUnavailable:
        pass
    session.refresh_from_db()
    state = session.scenario_state
    window = state["windows"][-1]
    start, end = scenarios.at(window["started_at"]), scenarios.at(window["ends_at"])
    declared = declared_of(session)
    extra = _extra(session, declared, state, start, end)
    result = scenarios.judged_window(state["schedule"], window, _blocked_between(session, start, end), extra,
                                     declared["completion"])
    taken = views._snapshot_waf(session, scenario_window=window["n"])
    result["fix"] = views._fix(session, (taken or {}).get("waf") or session.waf)
    result["judged_at"] = timezone.now().isoformat()

    def keep(state, held):
        state["windows"][-1]["result"] = result
    _update(session.pk, keep)
    return result

def _extra(session, declared, state, start, end) -> list:
    if declared["task_class"] == "judgement":
        return scenarios.judged_items([item["item"] for item in _items(session) if item["first"] < start],
                                      state["triage"])
    if declared["task_class"] == "detection":
        return _detection_reasons(session, state, start, end)
    return []

def _detection_reasons(session, state, start, end) -> list:
    fired = [entry for entry in scenarios.inside(state["schedule"], start, end) if entry.get("case_id")]
    expected = wargames.expectations(session.scenario)
    missed = []
    for entry in fired:
        signatures = list(session.detections.filter(source="suricata", marker=entry["case_id"]).order_by()
                          .values_list("signature", flat=True).distinct())
        if not signatures or scoreboard.corroborated(expected.get(entry["case"]), signatures, set()) is False:
            missed.append(entry["case"])
    served = session.customer_requests.filter(sent_at__gte=start, sent_at__lt=end).values("marker")
    noisy = session.detections.filter(source="suricata", marker__in=served).order_by().values("marker").distinct().count()
    return ([["scenario.fail.undetected", [", ".join(missed)]]] if missed else []) + (
        [["scenario.fail.noisy", [noisy]]] if noisy else [])

def _observe(session, now) -> None:
    adapter = None
    try:
        adapter = views._range(session)
        customers.refresh(session, adapter)
    except RangeUnavailable:
        pass
    try:
        views._ingest(session, RECENT)
    except (elastic.ElasticUnavailable, RangeUnavailable):
        pass
    if adapter is not None and time.monotonic() - _waf_read.get(session.pk, float("-inf")) >= settings.SCENARIO_WAF_POLL:
        _waf_read[session.pk] = time.monotonic()
        try:
            _waf_seen(session, views._waf_read(session)["file"], now)
        except (RangeUnavailable, Drifted):
            pass
    session.refresh_from_db(fields=["scenario_state"])
    last = scenarios.at(session.scenario_state["last_change"])
    if scenarios.idle(now, last, _blocked_between(session, now - scenarios.IDLE, now + MINUTE)) \
            and session.scenario_state.get("idle_offered") != session.scenario_state["last_change"]:
        stuck(session, "idle", "", idle_offered=session.scenario_state["last_change"])

def _waf_seen(session, text, now) -> str:
    version = scenarios.version_of(text)

    def seen(state, held):
        changes = state.setdefault("waf", [])
        if changes and changes[-1]["version"] == version:
            return
        changes.append({"at": now.isoformat(), "version": version})
        if len(changes) > 1:
            state["last_change"] = now.isoformat()
    _update(session.pk, seen)
    return version

def waf_applied(session, tuning, again) -> None:
    if session.course_scenario and session.scenario_state:
        version = _waf_seen(session, crs.rendered(tuning), timezone.now())
        if again:
            stuck(session, "waf", version)

def stuck(session, reason, about, **marks) -> None:
    if not (session.course_scenario and session.scenario_state):
        return

    def offer(state, held):
        state.update(marks)
        state["stuck"].append({"reason": reason, "about": about, "at": timezone.now().isoformat()})
        if state.get("offer") is None and len(state["hints"]) < len(declared_of(held).get("hints") or []):
            state["offer"] = {"reason": reason, "about": about, "at": timezone.now().isoformat()}
    _update(session.pk, offer)

def _items(session) -> list[dict]:
    replayed = {case.case_id for case in session.cases.all() if views._replayed(case)}
    cases = {case.case_id: case for case in session.cases.all() if case.case_id not in replayed}
    alerted = customers.alerted_markers(session)
    markers = [*cases, *alerted]
    if not markers:
        return []
    found = session.detections.filter(marker__in=markers)
    rules = (found.order_by().annotate(rule=KT("raw__details__ruleId"), sid=KT("raw__alert__signature_id"))
             .values("marker", "source", "signature", "rule", "sid")
             .annotate(n=Count("id"), first=Min("timestamp"), last=Max("timestamp")))
    firsts = found.order_by().values("marker").annotate(first_id=Min("id")).values_list("first_id", flat=True)
    shown = {row["marker"]: row for row in Detection.objects.filter(id__in=list(firsts)).annotate(
        method=KT("raw__request__method"), uri=KT("raw__request__uri"), http_method=KT("raw__http__http_method"),
        url=KT("raw__http__url"), status=KT("raw__http__status")).values(
        "marker", "method", "uri", "http_method", "url", "status")}
    sources: dict[str, list] = {}
    for marker, address in found.order_by().values_list("marker", "src_ip").distinct():
        if address:
            sources.setdefault(marker, []).append(address)
    grouped: dict[str, list] = {}
    for row in rules:
        grouped.setdefault(row["marker"], []).append(row)
    secret = session.browse_marker
    triage = (session.scenario_state or {}).get("triage") or {}
    items = [_item(scenarios.item_id(secret, marker), rows, shown.get(marker) or {}, sorted(sources.get(marker, [])),
                   triage) for marker, rows in grouped.items()]
    return sorted(items, key=lambda item: item["first"])

def _item(item, rows, shown, sources, triage) -> dict:
    engines = [{"engine": row["source"], "rule": str(row["rule"] or row["sid"] or ""), "signature": row["signature"],
                "count": row["n"]} for row in sorted(rows, key=lambda row: -row["n"])]
    waf = [row for row in rows if row["source"] == "modsecurity"]
    blocked = any(str(row["rule"] or "").startswith(CRS_TOTALS) for row in waf)
    return {
        "item": item,
        "first": min(row["first"] for row in rows),
        "last": max(row["last"] for row in rows),
        "alerts": sum(row["n"] for row in rows),
        "sources": sources,
        "request": {"method": shown.get("method") or shown.get("http_method") or "",
                    "path": shown.get("uri") or shown.get("url") or ""},
        "waf": "blocked" if blocked else "logged" if waf else "none",
        "status": 403 if blocked else int(shown["status"]) if str(shown.get("status") or "").isdigit() else None,
        "rules": engines[:SHOWN_RULES],
        **({"judged": {key: triage[item][key] for key in ("verdict", "succeeded", "right")}} if item in triage else {}),
    }

def _truths(session) -> dict[str, dict]:
    replayed = {case.case_id for case in session.cases.all() if views._replayed(case)}
    secret = session.browse_marker
    truths = {
        scenarios.item_id(secret, case.case_id): {"malicious": case.malicious, "succeeded": _succeeded(session, case)}
        for case in session.cases.all() if case.case_id not in replayed
    }
    for marker in customers.alerted_markers(session):
        truths[scenarios.item_id(secret, marker)] = {"malicious": False, "succeeded": False}
    return truths

def _succeeded(session, case) -> bool:
    if case.meta.get("loot"):
        return True
    if wargames.objective_model(session.scenario) != "effect_observed":
        return False
    return session.objectives.filter(achieved_at__gte=case.started_at - scoreboard.CLOCK_SKEW,
                                     achieved_at__lte=case.ended_at + scoreboard.CLOCK_SKEW).exists()

def triage_passed(session, judged) -> bool:
    truths = _truths(session)
    shown = {item["item"] for item in _items(session)}
    triage = (session.scenario_state or {}).get("triage") or {}
    right = [item for item in shown if (triage.get(item) or {}).get("right")]
    if judged == "all":
        return bool(shown) and len(right) == len(shown)
    wanted = judged == scenarios.ATTACK
    return any(truths.get(item, {}).get("malicious") is wanted for item in right)

def _scenario_session(session_id):
    session = get_object_or_404(Session, pk=session_id)
    if not session.course_scenario or not session.scenario_state:
        raise BadRequest(f"session {session.pk} does not run a scenario")
    return session

@require_http_methods(["GET", "POST"])
def triage(request, session_id):
    session = _scenario_session(session_id)
    if request.method == "GET":
        items = _items(session)
        return views._reply({"items": [dict(item, first=item["first"].isoformat(), last=item["last"].isoformat())
                                       for item in items[-SHOWN_ITEMS:]], "total": len(items),
                             "judged": sum(1 for item in items if item.get("judged", {}).get("right"))})
    views._refuse_closed(session)
    body = views._payload(request)
    item, verdict, succeeded = body.get("item"), body.get("verdict"), body.get("succeeded")
    if verdict not in scenarios.VERDICTS:
        raise BadRequest(f'"verdict" must be one of {list(scenarios.VERDICTS)}, got {verdict!r}')
    if verdict == scenarios.ATTACK and not isinstance(succeeded, bool):
        raise BadRequest(f'"succeeded" must be true or false for an attack, got {succeeded!r}')
    truth = _truths(session).get(item)
    if truth is None or item not in {shown["item"] for shown in _items(session)}:
        raise BadRequest(f'"item" must be one of the items GET triage/ lists, got {item!r}')
    result = scenarios.judged(truth, verdict, succeeded)

    def keep(state, held):
        state["triage"][item] = scenarios.kept_judgement(state["triage"].get(item), verdict, succeeded, result,
                                                         timezone.now().isoformat())
        return state["triage"][item]
    session, kept = _update(session.pk, keep)
    if scenarios.stuck_on_triage(kept):
        stuck(session, "triage", item)
    right = sum(1 for one in session.scenario_state["triage"].values() if one["right"])
    return views._reply(dict(result, item=item, tries=kept["tries"], right_so_far=right))

@require_http_methods(["GET"])
def scenario_status(request, session_id):
    return views._reply(status(_scenario_session(session_id)))

def status(session) -> dict:
    declared = declared_of(session)
    state = session.scenario_state
    now = timezone.now()
    windows = state["windows"]
    window = windows[-1] if windows else None
    alerts = session.detections.count()
    blocked = customers.counted(session.customer_requests.all())["blocked"]
    ends = scenarios.at(window["ends_at"]) if window and window["result"] is None else scenarios.at(state["ends_at"])
    opened = [hint["hint"] for hint in state["hints"]]
    return {
        **wargames.scenario_card(declared),
        "phase": scenarios.phase(state, session.ended_at is not None),
        "opened_at": state["opened_at"],
        "ends_at": state["ends_at"],
        "window_at": state["window_at"],
        "time_left": max(0, round((ends - now).total_seconds())),
        "live": {
            "customers_blocked_per_minute": _blocked_between(session, now - MINUTE, now + MINUTE),
            "alerted_per_minute": session.detections.filter(timestamp__gte=now - MINUTE).exclude(marker=None)
            .order_by().values("marker").distinct().count(),
            "objectives_lost": session.objectives.count(),
            "customers": {key: value for key, value in customers.counted(session.customer_requests.all()).items()
                          if key in ("sent", "served", "blocked")},
        },
        "window": window,
        "windows": len(windows),
        "completion": _completion(window),
        "cards": scenarios.cards_due(declared.get("cards") or [], alerts, blocked, bool(windows)),
        "text": declared["text"],
        "hints": {"offer": state.get("offer"), "opened": opened,
                  "left": len(declared.get("hints") or []) - len(opened)},
        "traffic": {"running": bool((session.traffic or {}).get("running")),
                    "error": (session.traffic or {}).get("error") or ""},
    }

def _completion(window) -> dict:
    if window is None:
        return {"state": "pending", "reasons": [], "fix": None}
    if window["result"] is None:
        return {"state": "open", "reasons": [], "fix": None}
    result = window["result"]
    return {"state": "passed" if result["passed"] else "failed", "reasons": result["reasons"], "fix": result["fix"]}

@require_http_methods(["POST"])
def verify_window(request, session_id):
    session = _scenario_session(session_id)
    views._refuse_closed(session)
    session, window = start_window(session, "learner")
    ensure_running()
    return views._reply(status(session), status=201)

@require_http_methods(["POST"])
def scenario_hints(request, session_id):
    session = _scenario_session(session_id)
    views._refuse_closed(session)
    declared = declared_of(session)

    def opened(state, held):
        taken = [hint["hint"] for hint in state["hints"]]
        left = [hint for hint in declared.get("hints") or [] if hint not in taken]
        if not left:
            raise Conflict(f"scenario {declared['id']} has no hint left")
        reason = (state.get("offer") or {}).get("reason") or "asked"
        used = {"hint": left[0], "level": "hint", "reason": reason, "at": timezone.now().isoformat()}
        state["hints"].append(used)
        state["offer"] = None
        held.hints = [*held.hints, used]
        return used
    session, used = _update(session.pk, opened)
    return views._reply({"hint": used["hint"], "text": f"{declared['text']}.hint.{used['hint']}",
                         "reason": used["reason"], **status(session)["hints"]}, status=201)

@require_http_methods(["GET"])
def scenario_debrief(request, session_id):
    session = _scenario_session(session_id)
    state = session.scenario_state
    judged = [window for window in state["windows"] if window.get("result")]
    if session.ended_at is None and not judged:
        raise Conflict("the debrief opens once a verification window is judged or the session is closed; the "
                       "attack schedule stays hidden until then")
    return views._reply(debrief(session))

def debrief(session) -> dict:
    declared = declared_of(session)
    state = session.scenario_state
    judged = [window for window in state["windows"] if window.get("result")]
    last = judged[-1]["result"] if judged else None
    opened = scenarios.at(state["opened_at"])
    cases = {case.case_id: case for case in session.cases.all()}
    marked = set(session.detections.filter(marker__in=list(cases)).order_by().values_list("marker", flat=True).distinct())
    timeline = [
        {"n": entry["n"], "case": entry["case"], "origin": entry["origin"], "state": entry["state"],
         "in_window": entry["in_window"], "outcome": entry.get("outcome"), "leaked": entry.get("leaked") or [],
         "at": round((scenarios.at(entry["fired_at"]) - opened).total_seconds()) if entry.get("fired_at") else entry["at"],
         "detected": entry.get("case_id") in marked, "error": entry.get("error") or ""}
        for entry in state["schedule"]
    ]
    windowed = {entry["n"] for window in judged for entry in scenarios.inside(
        state["schedule"], scenarios.at(window["started_at"]), scenarios.at(window["ends_at"]))}
    for entry in timeline:
        entry["in_window"] = entry["n"] in windowed
    before = {entry["case"]: entry["outcome"] for entry in timeline if not entry["in_window"] and entry["outcome"]}
    after = {entry["case"]: entry["outcome"] for entry in timeline if entry["in_window"] and entry["outcome"]}
    help_steps = lesson.help_counts(session.lesson_steps) if session.lesson_steps else {"hints": 0, "skipped": 0,
                                                                                      "done_for_me": 0}
    steps = {step["id"] for step in declared.get("steps") or []}
    triage = state["triage"]
    waf = next((taken["waf"] for taken in reversed(session.waf_snapshots or []) if taken.get("waf")), None)
    everything = customers.counted(session.customer_requests.all())
    return {
        "scenario": declared["id"],
        "title": f"{declared['text']}.title",
        "task_class": declared["task_class"],
        "overview": {
            "passed": last["passed"] if last else None, "verified": len(judged), "mode": session.mode,
            "fix": last["fix"] if last else None, "reasons": last["reasons"] if last else [],
            "steps": {"passed": sum(1 for step_id, kept in session.lesson_steps.items()
                                    if step_id in steps and kept.get("passed")), "total": len(steps)},
            "help": dict(help_steps, hints=help_steps["hints"] + len(state["hints"])),
        },
        "evidence": _evidence(session, cases),
        "change": views._change(session, waf),
        "cases": [{"name": name, "malicious": True, "before": before.get(name), "after": after.get(name)}
                  for name in dict.fromkeys(entry["case"] for entry in timeline)],
        "risk": [[f"scenario.risk.{last['fix']}", []]] if last and last["fix"] else [],
        "customers": {
            **{key: everything[key] for key in ("sent", "served", "blocked")},
            "in_window": [_blocked_between(session, scenarios.at(window["started_at"]), scenarios.at(window["ends_at"]))
                          for window in judged],
            "blocked_actions": customers.availability(session, set())["blocked_actions"],
        },
        "timeline": timeline,
        "triage": {"right": sum(1 for one in triage.values() if one["right"]),
                   "first_try": sum(1 for one in triage.values() if one.get("first_right")),
                   "judged": len(triage), "items": len(_items(session))},
        "at": {"opened": state["opened_at"], "verified": judged[-1]["ends_at"] if judged else None},
    }

def _evidence(session, cases) -> list[dict]:
    attacks = {case_id: case for case_id, case in cases.items() if case.meta.get("scheduled")}
    found = session.detections.filter(marker__in=list(attacks)).order_by("-timestamp")[:views.EVIDENCE_ROWS]
    return [
        {"id": detection.id, "source": detection.source, "signature": detection.signature,
         "method": views._request_of(detection.raw or {})[0], "path": views._request_of(detection.raw or {})[1],
         "phase": "attack", "case": attacks[detection.marker].name, "timestamp": detection.timestamp.isoformat()}
        for detection in found
    ]

def end(session) -> None:
    if not (session.course_scenario and session.scenario_state):
        return

    def cancel(state, held):
        for entry in state["schedule"]:
            if entry["state"] == scenarios.DUE:
                entry["state"] = scenarios.CANCELLED
    _update(session.pk, cancel)
    _observed.pop(session.pk, None)
    _waf_read.pop(session.pk, None)
