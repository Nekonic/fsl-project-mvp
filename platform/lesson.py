from __future__ import annotations

import difflib
import ipaddress
import re
from http import HTTPStatus

import disable

ANSWER = 3
SKIP_OFFERED = 4
SKIP_OFFERED_IN_FOUNDATIONS = 3
WRONGS_PER_HINT = 2
CRS_DEFAULT_LEVEL = 1
CRS_THRESHOLDS = {"inbound": 5, "outbound": 4}
CRS_TOTALS = ("949", "959", "980")
PASTED_ROW = re.compile(r"^\s*\|?\s*([\w.@+-]+)\s*[|:\s]\s*(\S+?)\s*\|?\s*$")
GROUPED_NUMBER = re.compile(r"\d{1,3}(,\d{3})+")
COUNTED = re.compile(r"\s*([\d,]+)\s*[^\W\d_]{1,2}\s*")
ORDER_SEPARATOR = re.compile(r"[\s,>\u2192]+")
TOTAL_SCORE = re.compile(r"Total Score: (\d+)")
NOCASE = re.compile(r"\bnocase\s*;|\bpcre\s*:\s*\"/.*/[A-Za-z]*i[A-Za-z]*\"")
REV = re.compile(r"[(;]\s*rev\s*:\s*(\d+)\s*[;)]")
BLOCKING_RULE = "949110"
OPTION = re.compile(r'\s*([\w.]+)\s*(?::\s*((?:"(?:\\.|[^"\\])*"|[^;])*))?;')
HEX = re.compile(r"\|([0-9A-Fa-f\s]*)\|")
URI_BUFFERS = ("http.uri", "http.uri.raw", "http.request_line", "pkt_data")
URI_MODIFIERS = ("http_uri", "http_raw_uri")
PRESENT, ABSENT = "present", "absent"
YES, NO = "yes", "no"
ALERTED_BY = {frozenset(): "none", frozenset({"suricata"}): "ids", frozenset({"modsecurity"}): "waf",
              frozenset({"suricata", "modsecurity"}): "both"}

def answered(check: dict, given: str, wrong: str) -> tuple[bool, list | None]:
    accepted = [_bare(str(value)) for value in check.get("accept", [])]
    if check.get("form") == "order":
        named = [_bare(name) for name in ORDER_SEPARATOR.split(given) if name]
        if named == accepted:
            return True, None
        if sorted(named) == sorted(accepted):
            return False, [f"{wrong}.order", []]
    elif {_bare(given), _bare(_ungrouped(given)), _bare(_ungrouped(_unit_dropped(given)))} & set(accepted):
        return True, None
    if given in check.get("known", []):
        return False, [f"{wrong}.{given}", []]
    said = next((rule["says"] for rule in check.get("wrong_if", []) if re.search(rule["match"], given)), None)
    return False, [f"{wrong}.{said}" if said else "lesson.check.wrong", []]

def status_said(code: int) -> list[str]:
    try:
        return [str(code), f"{code} {HTTPStatus(code).phrase}"]
    except ValueError:
        return [str(code)]

def an_address(text: str) -> bool:
    try:
        ipaddress.IPv4Address(text.strip())
    except ValueError:
        return False
    return True

def alerts_on(rule: str | None, uri: str) -> bool | None:
    body = (rule or "")[(rule or "").find("(") + 1:(rule or "").rfind(")")]
    contents, buffer = [], ""
    for name, value in OPTION.findall(body):
        if name == "pcre":
            return None
        if name == "content":
            negated = value.strip().startswith("!")
            contents.append({"text": _content(value), "negated": negated, "nocase": False, "uri": not buffer or buffer in URI_BUFFERS})
        elif name == "nocase" and contents:
            contents[-1]["nocase"] = True
        elif name in URI_MODIFIERS and contents:
            contents[-1]["uri"] = True
        elif name.startswith("http_") and contents:
            contents[-1]["uri"] = False
        elif name.startswith(("http.", "file.")) or name == "pkt_data":
            buffer = name
    if not contents:
        return None
    seen = lambda one: (one["text"].casefold() in uri.casefold()) if one["nocase"] else one["text"] in uri
    in_uri = [one for one in contents if one["uri"]]
    return bool(in_uri) and all(seen(one) != one["negated"] for one in in_uri)

def _content(value: str) -> str:
    quoted = value.strip().lstrip("!").strip()
    text = quoted[1:-1] if len(quoted) >= 2 and quoted[0] == quoted[-1] == '"' else quoted
    text = HEX.sub(lambda found: bytes.fromhex("".join(found[1].split())).decode("latin-1"), text)
    return re.sub(r"\\(.)", r"\1", text)

def _unit_dropped(text: str) -> str:
    found = COUNTED.fullmatch(text)
    return found[1] if found else text

def _ungrouped(text: str) -> str:
    return text.replace(",", "") if GROUPED_NUMBER.fullmatch(text.strip()) else text

def _bare(text: str) -> str:
    return "".join(text.split()).casefold()

def anomaly_totals(messages: list[str]) -> list[str]:
    return [found[1] for found in map(TOTAL_SCORE.search, messages) if found]

def ignores_case(rule: str) -> bool:
    return bool(NOCASE.search(rule))

def rev_of(rule: str | None) -> int:
    found = REV.search(rule or "")
    return int(found[1]) if found else 0

def raised_rev(rule: str, earlier: list[str]) -> bool:
    before = [rev_of(one) for one in earlier if one and not ignores_case(one)]
    return not before or rev_of(rule) > before[-1]

def alerted_by(engines: set[str]) -> str:
    return ALERTED_BY[frozenset(engines) & frozenset({"suricata", "modsecurity"})]

def penalty(difficulty: int, detected: bool) -> int:
    return difficulty * (1 if detected else 2)

def detected_penalty(tiers: list[dict], key: str) -> int | None:
    found = next((tier for tier in tiers if tier.get("key") == key), None)
    return penalty(int(found["difficulty"]), True) if found else None

def rule_of(raw: dict) -> str:
    return str((raw.get("details") or {}).get("ruleId") or (raw.get("alert") or {}).get("signature_id") or "")

def server_errors(records: list[dict]) -> list[dict]:
    return [record for record in records
            if str(((record.get("transaction") or {}).get("response") or {}).get("http_code") or "") == "500"]

def server_error_sources(records: list[dict]) -> list[str]:
    return sorted({str(source) for record in server_errors(records)
                   if (source := (record.get("transaction") or {}).get("client_ip"))})

def fix_class(waf: dict | None, posture: dict | None) -> str | None:
    if not waf:
        return None
    posture = posture or {}
    level = waf.get("paranoia") or CRS_DEFAULT_LEVEL
    if posture.get("paranoia") and level < posture["paranoia"]:
        return "level"
    if any(_threshold(waf, way) > _threshold(posture, way) for way in CRS_THRESHOLDS):
        return "threshold"
    added = [entry for entry in waf.get("exclusions") or [] if entry not in (posture.get("exclusions") or [])]
    if not added:
        return None
    if any(not entry["target"] for entry in added):
        return "rule"
    if any(not entry["path"] for entry in added):
        return "target"
    return "path_target"

def _threshold(tuning: dict, way: str) -> int:
    return (tuning.get("thresholds") or {}).get(way, CRS_THRESHOLDS[way])

def config_diff(before: str, after: str) -> list[str]:
    return [
        line for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]

def exclusions_changed(before: list, after: list) -> dict:
    return {"added": [entry for entry in after if entry not in before],
            "removed": [entry for entry in before if entry not in after]}

def records(lesson_steps: dict | None, lesson_id: str) -> dict:
    return (lesson_steps or {}).get(lesson_id) or {}

def help_counts(steps: dict) -> dict:
    kept = list(steps.values())
    return {
        "hints": sum(1 for step in kept if step.get("hint")),
        "skipped": sum(1 for step in kept if step.get("skipped") and not step.get("passed")),
        "retried": sum(1 for step in kept if step.get("passed") and step.get("tries")),
    }

def objective_outcome(row: dict | None) -> str | None:
    if row is None:
        return None
    return "kept" if not row["lost"] else "detected" if row["detected"] else "undetected"

def rules_named(messages: list[dict]) -> list[str]:
    found = set()
    for message in messages:
        rule = str((message.get("details") or {}).get("ruleId") or "")
        if rule and not rule.startswith(CRS_TOTALS):
            found.add(rule)
    return sorted(found)

def added_rules(live: str, baseline: str) -> list[int]:
    started = {sid: " ".join(disable.find(baseline, sid).split()) for sid in disable.sids(baseline)}
    return sorted(sid for sid in disable.sids(live)
                  if started.get(sid) != " ".join(disable.find(live, sid).split()))

def pasted_rows(text: str, parsed: list) -> list:
    return parsed or [found.groups() for found in map(PASTED_ROW.match, text.splitlines()) if found]
