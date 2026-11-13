from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "platform"))

from ingest.elastic import normalize_all
from scoring.correlate import correlate
from scoring.types import CaseRecord, DetectionRecord
import scoreboard

LEGS = {"firewall.localdomain": "edge", "edge": "edge", "cr-wargame-host": "estate", "wargame-host": "estate", "waf": "modsec"}

def leg_of(doc):
    return LEGS.get(((doc.get("log") or {}).get("syslog") or {}).get("hostname"), "?")

def opened(path):
    return gzip.open(path, "rt") if str(path).endswith(".gz") else open(path)

def documents(path):
    with opened(path) as lines:
        return [tuple(json.loads(line)) for line in lines if line.strip()]

def at(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))

def header(http, name):
    return [h.get("value") for h in (http or {}).get("request_headers") or [] if str(h.get("name", "")).lower() == name]

def score(docs, cases):
    detections = normalize_all(docs)
    records = [CaseRecord(case_id=c["case_id"], name=c["name"], malicious=c["malicious"],
                          correlation=c.get("correlation") or "marker", source_ip=c.get("source_ip"),
                          started_at=at(c["started_at"]), ended_at=at(c["ended_at"])) for c in cases]
    result = correlate(records, [DetectionRecord(d["detection_id"], d["timestamp"], d["src_ip"], d["marker"]) for d in detections])
    by_id = {d["detection_id"]: d for d in detections}
    signatures = {d["detection_id"]: d["signature"] for d in detections}
    indiscriminate = {signatures[i] for m in result.matches if not m.malicious for i in m.detection_ids}
    expect = {c["case_id"]: c.get("expect") or "" for c in cases}
    by_marker = {}
    for doc_id, doc in docs:
        if (doc.get("event") or {}).get("module") != "suricata" or doc.get("event_type") != "http":
            continue
        for marker in header(doc.get("http"), "x-request-id"):
            by_marker.setdefault(marker, []).append(doc)
    rows = []
    for m in result.matches:
        legs = {"edge": set(), "estate": set(), "modsec": set()}
        sources = {"edge": set(), "estate": set(), "modsec": set()}
        counts = {"edge": 0, "estate": 0, "modsec": 0}
        for i in m.detection_ids:
            d = by_id[i]
            raw = d["raw"]
            if d["source"] == "suricata":
                leg = leg_of(raw)
                legs[leg].add(str((raw.get("alert") or {}).get("signature_id")))
                sources[leg].add(d["src_ip"])
            else:
                leg = "modsec"
                legs[leg].add(str((raw.get("details") or {}).get("ruleId")))
                sources[leg].add(d["src_ip"])
            counts[leg] += 1
        seen = {"edge": set(), "estate": set(), "estate_xff": set()}
        for doc in by_marker.get(m.case_id, []):
            leg = leg_of(doc)
            seen[leg].add(doc.get("src_ip"))
            if leg == "estate":
                seen["estate_xff"].update(header(doc.get("http"), "x-forwarded-for"))
        rows.append({
            "name": m.name,
            "verdict": ("TP" if m.detected else "FN") if m.malicious else ("FP" if m.detected else "TN"),
            "corroborated": scoreboard.corroborated(expect[m.case_id], [signatures[i] for i in m.detection_ids], indiscriminate),
            "sids": {k: sorted(v) for k, v in legs.items()},
            "alert_sources": {k: sorted(map(str, v)) for k, v in sources.items()},
            "http_sources": {k: sorted(map(str, v)) for k, v in seen.items()},
            "counts": counts,
        })
    return rows

if __name__ == "__main__":
    docs = documents(sys.argv[1])
    cases = json.loads(Path(sys.argv[2]).read_text())
    json.dump(score(docs, cases), sys.stdout, indent=1, sort_keys=True)
