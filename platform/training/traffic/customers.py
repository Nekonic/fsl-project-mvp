from __future__ import annotations

import json
import logging
import random
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import yaml
from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from cr import errors
from domain.traffic import DEFAULT_RATE, allocated, rate_of
from domain.types import ACTION_CASE, CORRELATION_MARKER, ActionRecord
from training.attack import actions as attack
from training.attack import origins as attack_origins
from training.models import CustomerRequest, Round

BENIGN_EVERY_S = 60
BENIGN_ACTION = "benign"
PLATFORM_USER = "platform"
RATE = DEFAULT_RATE
FLOWS = 2000
PULL_LIMIT = 1 << 20
KOREAN = "kr"
KOREAN_WRITES_ENGLISH = 0.15
LANGUAGES = {KOREAN: "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7", "": "en-US,en;q=0.9"}
SEARCHES = ("search-korean", "search-english", "search-unusual")
COMMENTS = {"comment": None, "comment-code": "code"}
ACTIONS = ("home", "newest", "post", *SEARCHES, "login", *COMMENTS)
NEEDED = ("users", "origins", "accounts", "posts", "agents", "searches", "comments", "profiles", "default_profile")

logger = logging.getLogger(__name__)


class TrafficRefused(ValueError):
    pass


def setup(found: Round) -> Mapping[str, Any]:
    return found.snapshot.get("round") or {}


def benign_cases(found: Round) -> list[str]:
    declared = setup(found).get("benign_cases")
    if declared:
        return list(declared)
    return [case["name"] for case in attack.declared_cases(found)
            if case.get("malicious") is False and "tool" not in case]


def every(found: Round) -> timedelta:
    return timedelta(seconds=int(setup(found).get("benign_every_s") or BENIGN_EVERY_S))


def benign_sent(found: Round):
    return CustomerRequest.objects.filter(round=found).exclude(benign_case=None)


def passes(found: Round) -> int:
    names = benign_cases(found)
    if not names:
        return 0
    counted = dict(benign_sent(found).values_list("benign_case").annotate(sent=Count("id")))
    return min(counted.get(name, 0) for name in names)


def due(found: Round, now: datetime) -> bool:
    last = benign_sent(found).order_by("-sent_at").values_list("sent_at", flat=True).first()
    return last is None or now - last >= every(found)


def origin_of(origins: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    return {address: origin["id"] for origin in origins for address in origin["addresses"]}


def fire_pass(found: Round) -> int:
    origins = attack_origins.customer_origins(found)
    sources = [address for origin in origins for address in origin["addresses"]]
    if not sources:
        raise errors.Unavailable(code="attacker_unavailable")
    home = origin_of(origins)
    fired = 0
    for at, name in enumerate(benign_cases(found)):
        source = sources[at % len(sources)]
        try:
            sent = attack.fire_benign(found, name, source)
        except errors.DomainError:
            logger.exception("round %s: the benign case %s did not reach the target", found.pk, name)
            continue
        CustomerRequest.objects.create(
            round=found, marker=sent.marker, action=BENIGN_ACTION, user=PLATFORM_USER, origin=home.get(source, ""),
            source_ip=source, method=sent.method, path=sent.path, status=sent.status, sent_at=sent.started,
            elapsed_ms=max(0, int((sent.ended - sent.started).total_seconds() * 1000)), benign_case=name)
        fired += 1
    return fired


def benign_records(found: Round) -> tuple[ActionRecord, ...]:
    return tuple(
        ActionRecord(action_id=f"benign-{row.pk}", kind=ACTION_CASE, marker=row.marker,
                     correlation=CORRELATION_MARKER, source_ip=row.source_ip, started_at=row.sent_at,
                     ended_at=row.sent_at + timedelta(milliseconds=row.elapsed_ms), case_id=row.benign_case,
                     malicious=False, method=row.method, path=row.path)
        for row in benign_sent(found).order_by("sent_at", "id"))


def declared_traffic(wargame_id: str) -> dict[str, Any] | None:
    path = Path(settings.CR_SOURCE) / "wargames" / wargame_id / "traffic.yaml"
    if not path.is_file():
        return None
    return checked(yaml.safe_load(path.read_text(encoding="utf-8")))


def checked(declared: Any) -> dict[str, Any]:
    if not isinstance(declared, dict):
        raise TrafficRefused("the customers' traffic is a mapping")
    missing = [key for key in NEEDED if key not in declared]
    if missing:
        raise TrafficRefused(f"missing {', '.join(missing)}")
    for name, weights in declared["profiles"].items():
        unknown = sorted(set(weights) - set(ACTIONS))
        if unknown:
            raise TrafficRefused(f"profile {name!r} names no action {unknown}")
        if any(action in SEARCHES and not declared["searches"].get(action.removeprefix("search-"))
               for action in weights):
            raise TrafficRefused(f"profile {name!r} searches with no term declared")
        if any(COMMENTS.get(action) and not declared["comments"].get(COMMENTS[action]) for action in weights):
            raise TrafficRefused(f"profile {name!r} posts a comment kind with no comment declared")
    if declared["default_profile"] not in declared["profiles"]:
        raise TrafficRefused(f"default_profile {declared['default_profile']!r} is not a profile")
    if not declared["posts"] or not declared["agents"]:
        raise TrafficRefused("customers need at least one post and one browser")
    return declared


def personas(declared: Mapping[str, Any], available: Sequence[Mapping[str, Any]], rng: random.Random) -> list[dict]:
    offered = {origin["id"]: origin for origin in available}
    weights = {origin: weight for origin, weight in declared["origins"].items() if origin in offered and weight > 0}
    if not weights:
        raise errors.Unavailable(code="attacker_unavailable")
    accounts = list(declared["accounts"])
    turns: dict[str, int] = {}
    found = []
    for index, home in enumerate(allocated(weights, int(declared["users"]))):
        origin = offered[home]
        addresses = list(origin.get("addresses") or [""])
        turn = turns.get(home, 0)
        turns[home] = turn + 1
        found.append({
            "id": f"u{index + 1:02d}", "origin": home, "bind": addresses[turn % len(addresses)],
            "target": origin["target_url"], "agent": rng.choice(declared["agents"]),
            "language": LANGUAGES.get(home, LANGUAGES[""]),
            "account": accounts.pop(0) if accounts and (home == KOREAN or KOREAN not in weights) else None,
        })
    return found


def comment_text(declared: Mapping[str, Any], persona: Mapping[str, Any], rng: random.Random,
                 kind: str | None) -> str:
    if kind:
        return rng.choice(declared["comments"][kind])
    korean = persona["origin"] == KOREAN and rng.random() >= KOREAN_WRITES_ENGLISH
    return rng.choice(declared["comments"]["korean" if korean else "english"])


def steps(declared: Mapping[str, Any], action: str, persona: Mapping[str, Any], rng: random.Random) -> list[dict]:
    if action == "home":
        return [{"step": "home", "method": "GET", "path": "/"}]
    if action == "newest":
        return [{"step": "home", "method": "GET", "path": "/?" + urlencode({"sort": "-created_at"})}]
    if action == "post":
        return [{"step": "post", "method": "GET", "path": f"/posts/{rng.choice(declared['posts'])}/"}]
    if action in SEARCHES:
        term = rng.choice(declared["searches"][action.removeprefix("search-")])
        return [{"step": "search", "method": "GET", "path": "/search/?" + urlencode({"q": term})}]
    if action == "login":
        account = persona["account"]
        return [{"step": "login.form", "method": "GET", "path": "/accounts/login/"},
                {"step": "login", "method": "POST", "path": "/accounts/login/", "csrf": True, "follow": True,
                 "form": {"username": account["username"], "password": account["password"], "next": ""}}]
    post = rng.choice(declared["posts"])
    return [{"step": "post", "method": "GET", "path": f"/posts/{post}/"},
            {"step": "comment", "method": "POST", "path": f"/posts/{post}/comments/", "csrf": True, "follow": True,
             "form": {"body": comment_text(declared, persona, rng, COMMENTS[action])}}]


def flows(declared: Mapping[str, Any], profile: str, users: Sequence[Mapping[str, Any]], rng: random.Random,
          count: int = FLOWS) -> list[dict]:
    weights = declared["profiles"][profile]
    rendered = []
    for _ in range(count):
        index = rng.randrange(len(users))
        persona = users[index]
        allowed = [action for action in weights if weights[action] > 0 and (action != "login" or persona["account"])]
        action = rng.choices(allowed, [weights[action] for action in allowed])[0]
        rendered.append({"user": index, "action": action, "steps": steps(declared, action, persona, rng)})
    return rendered


def plan(declared: Mapping[str, Any], profile: str, users: Sequence[Mapping[str, Any]], host: str, seed: str,
         rate: float = RATE, count: int = FLOWS) -> dict:
    return {"host": host, "rate": rate, "profile": profile, "users": list(users),
            "flows": flows(declared, profile, users, random.Random(f"{seed}:{profile}"), count)}


def records(chunk: str) -> tuple[list[dict], int]:
    complete = chunk[:chunk.rfind("\n") + 1]
    found = []
    for line in complete.splitlines():
        try:
            record = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("marker"):
            found.append(record)
    return found, len(complete.encode())


def row_of(found: Round, record: Mapping[str, Any]) -> CustomerRequest:
    return CustomerRequest(
        round=found, marker=str(record["marker"])[:64], action=str(record.get("action", ""))[:32],
        user=str(record.get("user", ""))[:32], origin=str(record.get("origin", ""))[:32],
        source_ip=record.get("source_ip") or None, method=str(record.get("method", ""))[:8],
        path=str(record.get("path", "")), status=int(record.get("status") or 0),
        refused_by=str(record.get("refused_by") or "")[:8],
        sent_at=parse_datetime(str(record.get("sent_at") or "")) or timezone.now(),
        elapsed_ms=max(0, int(record.get("elapsed_ms") or 0)))


def kept(found: Round, **changed) -> dict:
    found.traffic = {**found.traffic, **changed}
    Round.objects.filter(pk=found.pk).update(traffic=found.traffic)
    return found.traffic


def pull(found: Round) -> int:
    offset, taken = int(found.traffic.get("offset", 0)), 0
    while True:
        chunk = attack.customer_records(found, offset, PULL_LIMIT)
        rows, used = records(chunk)
        CustomerRequest.objects.bulk_create([row_of(found, record) for record in rows], ignore_conflicts=True)
        offset, taken = offset + used, taken + len(rows)
        kept(found, offset=offset)
        if used == 0 or len(chunk.encode()) < PULL_LIMIT:
            return taken


def profile_of(found: Round, declared: Mapping[str, Any]) -> str:
    chosen = setup(found).get("traffic") or declared["default_profile"]
    return chosen if chosen in declared["profiles"] else declared["default_profile"]


def start(found: Round) -> bool:
    declared = declared_traffic(found.snapshot["wargame"]["id"])
    if declared is None:
        return False
    profile = profile_of(found, declared)
    users = personas(declared, attack_origins.customer_origins(found), random.Random(str(found.pk)))
    hosts = list(found.snapshot["wargame"]["hosts"])
    attack.start_customers(found, plan(declared, profile, users, hosts[0], str(found.pk), rate=rate_of(declared)))
    kept(found, running=True, profile=profile, offset=0, error="")
    return True


def guarded(found: Round, what: str, work) -> None:
    try:
        work(found)
    except (errors.DomainError, TrafficRefused, OSError) as failed:
        logger.warning("round %s: %s failed: %s", found.pk, what, failed)
        kept(found, error=f"{what}: {failed}"[:300])


def begin(found: Round) -> None:
    guarded(found, "starting the customers", start)


def catch_up(found: Round, now: datetime | None = None) -> None:
    if found.traffic.get("running"):
        guarded(found, "reading the customers' records", pull)
    if due(found, now or timezone.now()):
        guarded(found, "the benign pass", fire_pass)


def stop(found: Round) -> None:
    if not found.traffic.get("running"):
        return
    guarded(found, "stopping the customers", lambda one: attack.stop_customers(one))
    guarded(found, "reading the customers' records", pull)
    kept(found, running=False)
