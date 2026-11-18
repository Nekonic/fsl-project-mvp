from __future__ import annotations

import json
import random
from typing import Any
from urllib.parse import urlencode

RATE_DEFAULT = 1.0
RATE_CAP = 50.0
FLOWS = 2000
KOREAN = "kr"
KOREAN_WRITES_ENGLISH = 0.15
LANGUAGES = {
    KOREAN: "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "": "en-US,en;q=0.9",
}
SEARCHES = ("search-korean", "search-english", "search-unusual")
COMMENTS = {"comment": None, "comment-code": "code"}
ACTIONS = ("home", "newest", "post", *SEARCHES, "login", *COMMENTS)
NEEDED = ("users", "origins", "accounts", "posts", "agents", "searches", "comments", "profiles", "default_profile")

class InvalidTraffic(ValueError):
    pass

class NoOrigin(RuntimeError):
    pass

def checked(declared: Any, source) -> dict[str, Any]:
    if not isinstance(declared, dict):
        raise InvalidTraffic(f"{source}: the customers' traffic is a mapping")
    missing = [key for key in NEEDED if key not in declared]
    if missing:
        raise InvalidTraffic(f"{source}: missing {', '.join(missing)}")
    for name, weights in declared["profiles"].items():
        unknown = sorted(set(weights) - set(ACTIONS))
        if unknown:
            raise InvalidTraffic(f"{source}: profile {name!r} names no action {unknown}; actions are {ACTIONS}")
        empty = [action for action in weights if action in SEARCHES
                 and not declared["searches"].get(action.removeprefix("search-"))]
        if empty:
            raise InvalidTraffic(f"{source}: profile {name!r} searches {empty} and no term is declared for them")
        unwritten = [action for action in weights if COMMENTS.get(action) and not declared["comments"].get(COMMENTS[action])]
        if unwritten:
            raise InvalidTraffic(f"{source}: profile {name!r} posts {unwritten} and no comment is declared for them")
    if declared["default_profile"] not in declared["profiles"]:
        raise InvalidTraffic(f"{source}: default_profile {declared['default_profile']!r} is not a profile")
    if not declared["posts"] or not declared["agents"]:
        raise InvalidTraffic(f"{source}: customers need at least one post and one browser")
    return declared

def rate_of(given: Any, kept: float | None = None) -> float:
    if given is None:
        return kept or RATE_DEFAULT
    if isinstance(given, bool) or not isinstance(given, (int, float)) or not 0 < given <= RATE_CAP:
        raise ValueError(f'"rate" is requests per second above 0 and at most {RATE_CAP:g}, got {given!r}')
    return float(given)

def profile_of(declared: dict[str, Any], given: Any, kept: str | None = None) -> str:
    chosen = given if given is not None else kept or declared["default_profile"]
    if chosen not in declared["profiles"]:
        raise ValueError(f'"profile" must be one of {sorted(declared["profiles"])}, got {given!r}')
    return chosen

def allocated(weights: dict[str, float], total: int) -> list[str]:
    whole = sum(weights.values())
    shares = {origin: total * weight / whole for origin, weight in weights.items()}
    counts = {origin: int(share) for origin, share in shares.items()}
    left = total - sum(counts.values())
    for origin in sorted(shares, key=lambda o: (counts[o] - shares[o], o))[:left]:
        counts[origin] += 1
    return [origin for origin in sorted(weights, key=lambda o: (-weights[o], o)) for _ in range(counts[origin])]

def personas(declared: dict[str, Any], available: list[dict], rng: random.Random) -> list[dict]:
    offered = {origin["id"]: origin for origin in available}
    weights = {origin: weight for origin, weight in declared["origins"].items()
               if origin in offered and weight > 0}
    if not weights:
        raise NoOrigin(
            f"the range offers customers none of the origins they come from "
            f"({', '.join(sorted(declared['origins']))}) apart from the attacker's own; offered: "
            f"{', '.join(sorted(offered)) or 'none'}"
        )
    homes = allocated(weights, int(declared["users"]))
    accounts = list(declared["accounts"])
    turns: dict[str, int] = {}
    found = []
    for index, home in enumerate(homes):
        origin = offered[home]
        addresses = origin.get("addresses") or [""]
        turn = turns.get(home, 0)
        turns[home] = turn + 1
        found.append({
            "id": f"u{index + 1:02d}",
            "origin": home,
            "bind": addresses[turn % len(addresses)],
            "target": origin["target_url"],
            "agent": rng.choice(declared["agents"]),
            "language": LANGUAGES.get(home, LANGUAGES[""]),
            "account": accounts.pop(0) if accounts and (home == KOREAN or KOREAN not in weights) else None,
        })
    return found

def _search(term: str) -> str:
    return "/search/?" + urlencode({"q": term})

def _comment_text(declared: dict[str, Any], persona: dict, rng: random.Random, kind: str | None = None) -> str:
    if kind:
        return rng.choice(declared["comments"][kind])
    korean = persona["origin"] == KOREAN and rng.random() >= KOREAN_WRITES_ENGLISH
    return rng.choice(declared["comments"]["korean" if korean else "english"])

def steps(declared: dict[str, Any], action: str, persona: dict, rng: random.Random) -> list[dict]:
    if action == "home":
        return [{"step": "home", "method": "GET", "path": "/"}]
    if action == "newest":
        return [{"step": "home", "method": "GET", "path": "/?" + urlencode({"sort": "-created_at"})}]
    if action == "post":
        return [{"step": "post", "method": "GET", "path": f"/posts/{rng.choice(declared['posts'])}/"}]
    if action in SEARCHES:
        terms = declared["searches"][action.removeprefix("search-")]
        return [{"step": "search", "method": "GET", "path": _search(rng.choice(terms))}]
    if action == "login":
        account = persona["account"]
        return [
            {"step": "login.form", "method": "GET", "path": "/accounts/login/"},
            {"step": "login", "method": "POST", "path": "/accounts/login/", "csrf": True, "follow": True,
             "form": {"username": account["username"], "password": account["password"], "next": ""}},
        ]
    if action in COMMENTS:
        post = rng.choice(declared["posts"])
        return [
            {"step": "post", "method": "GET", "path": f"/posts/{post}/"},
            {"step": "comment", "method": "POST", "path": f"/posts/{post}/comments/", "csrf": True, "follow": True,
             "form": {"body": _comment_text(declared, persona, rng, COMMENTS[action])}},
        ]
    raise InvalidTraffic(f"no action {action!r}; actions are {ACTIONS}")

def flows(declared: dict[str, Any], profile: str, users: list[dict], rng: random.Random,
          count: int = FLOWS) -> list[dict]:
    weights = declared["profiles"][profile]
    rendered = []
    for _ in range(count):
        index = rng.randrange(len(users))
        persona = users[index]
        allowed = [action for action in weights if weights[action] > 0
                   and (action != "login" or persona["account"])]
        action = rng.choices(allowed, [weights[action] for action in allowed])[0]
        rendered.append({"user": index, "action": action, "steps": steps(declared, action, persona, rng)})
    return rendered

def plan(declared: dict[str, Any], profile: str, rate: float, users: list[dict], host: str,
         seed: str, count: int = FLOWS) -> dict:
    return {
        "host": host,
        "rate": rate,
        "profile": profile,
        "users": users,
        "flows": flows(declared, profile, users, random.Random(f"{seed}:{profile}"), count),
    }

def records(chunk: str) -> tuple[list[dict], int, int]:
    complete = chunk[:chunk.rfind("\n") + 1]
    found, garbled = [], 0
    for line in complete.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            garbled += 1
            continue
        if isinstance(record, dict) and record.get("marker"):
            found.append(record)
        else:
            garbled += 1
    return found, len(complete.encode()), garbled
