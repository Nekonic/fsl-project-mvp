import time
from datetime import datetime, timedelta, timezone

import pytest
import requests

from conftest import from_attacker

ELASTIC = "http://localhost:9200"
INDEX = "fsl-logs-*"
TOLERANCE = 0.5

def _iso(value: str) -> datetime:
    text = str(value).replace("Z", "+00:00")
    if len(text) >= 5 and text[-5] in "+-" and ":" not in text[-5:]:
        text = text[:-2] + ":" + text[-2:]
    return datetime.fromisoformat(text)

def _ctime(value: str) -> datetime:
    return datetime.strptime(str(value), "%a %b %d %H:%M:%S %Y").replace(
        tzinfo=timezone.utc
    )

def _since(fsl_source: str, since: datetime) -> list[dict]:
    body = {
        "size": 200,
        "sort": [{"@timestamp": "desc"}],
        "query": {"term": {"fsl_source": fsl_source}},
    }
    hits = requests.post(f"{ELASTIC}/{INDEX}/_search", json=body, timeout=30).json()
    fresh = []
    for hit in hits.get("hits", {}).get("hits", []):
        doc = hit["_source"]
        stamped = doc.get("@timestamp")
        if stamped and _iso(stamped) >= since:
            fresh.append(doc)
    return fresh

@pytest.fixture(scope="module")
def after_a_fresh_attack(stack_is_up):
    since = datetime.now(timezone.utc) - timedelta(seconds=2)
    from_attacker("/search/?q=%27%20OR%201%3D1--%20")
    deadline = time.time() + 60
    while time.time() < deadline:
        if _since("suricata", since) and _since("modsecurity", since):
            break
        time.sleep(3)
    return since

def test_suricata_at_is_the_event_time(after_a_fresh_attack):
    docs = _since("suricata", after_a_fresh_attack)
    assert docs, "no fresh Suricata documents reached Elasticsearch to check"

    for doc in docs:
        drift = abs((_iso(doc["@timestamp"]) - _iso(doc["timestamp"])).total_seconds())
        assert drift < TOLERANCE, (
            f"@timestamp {doc['@timestamp']} is {drift:.1f}s off the event's own "
            f"time {doc['timestamp']}: evidence is still selected by read time, so "
            f"a late-shipped alert falls out of the window it belongs in"
        )

def test_modsecurity_at_is_the_event_time(after_a_fresh_attack):
    docs = _since("modsecurity", after_a_fresh_attack)
    assert docs, "no fresh ModSecurity documents reached Elasticsearch to check"

    for doc in docs:
        event = _ctime(doc["transaction"]["time_stamp"])
        drift = abs((_iso(doc["@timestamp"]) - event).total_seconds())
        assert drift < TOLERANCE, (
            f"@timestamp {doc['@timestamp']} is {drift:.1f}s off the event's own "
            f"time {doc['transaction']['time_stamp']}: evidence is still selected "
            f"by read time, so a late-shipped alert falls out of its window"
        )
