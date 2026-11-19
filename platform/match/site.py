from __future__ import annotations

import itertools
import threading
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie

from django.utils import timezone

from attack import service as attack
from cr import errors
from match import auth
from match.models import Round, Seat

KEPT_PER_ROUND = 200
PASSED_ON = ("Accept", "Accept-Language", "Content-Type", "User-Agent")
NOT_RETURNED = frozenset({"connection", "content-length", "keep-alive", "set-cookie", "transfer-encoding",
                          "content-encoding"})
LESSON = "lesson"

kept: dict[int, deque] = {}
jars: dict[tuple[int, str], dict[str, str]] = {}
numbers = itertools.count(1)
guard = threading.Lock()


@dataclass(frozen=True)
class Fetched:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: str
    hp_left: int | None


def attack_seat(found: Round, seated: Sequence[Seat]) -> Seat | None:
    if found.kind == LESSON:
        return None
    return next((seat for seat in seated if seat.side == "attack"), None)


def checked_host(found: Round, host: str) -> str:
    if host not in list(found.snapshot.get("wargame", {}).get("hosts") or ()):
        raise errors.NotFound()
    return host


def cookie_header(round_id: int, host: str) -> str:
    with guard:
        jar = dict(jars.get((round_id, host), {}))
    return "; ".join(f"{name}={value}" for name, value in jar.items())


def keep_cookies(round_id: int, host: str, headers: Sequence[tuple[str, str]]) -> None:
    for name, value in headers:
        if name.lower() != "set-cookie":
            continue
        try:
            parsed = SimpleCookie(value)
        except CookieError:
            continue
        with guard:
            jar = jars.setdefault((round_id, host), {})
            for morsel in parsed.values():
                if morsel["max-age"] == "0":
                    jar.pop(morsel.key, None)
                else:
                    jar[morsel.key] = morsel.value


def browse_source(found: Round) -> str:
    sources = attack.customer_addresses(found)
    if not sources:
        raise errors.Unavailable(code="attacker_unavailable")
    return sources[0]


def remember(found: Round, method: str, host: str, path: str, status: int, size: int) -> None:
    with guard:
        kept.setdefault(found.pk, deque(maxlen=KEPT_PER_ROUND)).append({
            "id": next(numbers), "at": timezone.now(), "method": method, "url": f"http://{host}{path}",
            "status": status, "size": size})


def browse(found: Round, seated: Sequence[Seat], method: str, host: str, path: str,
           headers: Mapping[str, str], body: str | None) -> Fetched:
    auth.refuse_write(found)
    host = checked_host(found, host)
    passed = {name: headers[name] for name in PASSED_ON if headers.get(name)}
    cookie = cookie_header(found.pk, host)
    if cookie:
        passed["Cookie"] = cookie
    seat = attack_seat(found, seated)
    if seat is not None:
        sent = attack.send(found, seat, method, path, host=host, headers=passed, body=body, kind="site")
        left = attack.hp(found).left
    else:
        sent = attack.send_as_customer(found, browse_source(found), method, path, host=host, headers=passed,
                                       body=body, marker=found.lease.browse_marker)
        left = None
    keep_cookies(found.pk, host, sent.headers)
    remember(found, method, host, path, sent.status, len(sent.body))
    returned = tuple((name, value) for name, value in sent.headers if name.lower() not in NOT_RETURNED)
    return Fetched(status=sent.status, headers=returned, body=sent.body, hp_left=left)


def requests_of(found: Round, after: int = 0) -> list[dict]:
    with guard:
        return [record for record in kept.get(found.pk, ()) if record["id"] > after]


def forget(round_id: int) -> None:
    with guard:
        kept.pop(round_id, None)
        for key in [key for key in jars if key[0] == round_id]:
            del jars[key]
