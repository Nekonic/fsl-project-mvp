from __future__ import annotations

import hmac
import json
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import requests

from bots import tools
from bots.pace import Pace, counted, pace_wait

PACE_LIMITED = "pace_limited"
NOT_AT_THIS_STEP = "not_at_this_step"
NOT_SIGNED_IN = "not_signed_in"
EVERY_CASE = "*"
CASE_FIRING = "attack_fire_case"
PASSED_HEADERS = ("Content-Type", "X-Origin", "X-Origins-Left", "Retry-After")
UPSTREAM_SECONDS = 900.0


@dataclass(frozen=True)
class Refusal:
    status: int
    code: str
    params: dict = field(default_factory=dict)

    def body(self) -> bytes:
        error = {"path": "", "code": self.code, **({"params": self.params} if self.params else {})}
        return json.dumps({"errors": [error]}).encode()


@dataclass(frozen=True)
class Route:
    operation: str
    tag: str | None
    method: str
    pattern: re.Pattern


def routes(schema: dict) -> list[Route]:
    made = []
    for name, (method, path, operation) in tools.operation_entries(schema).items():
        shape = re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>[^/]+)", re.escape(path))
        made.append(Route(name, tools.side_of(operation), method.upper(), re.compile(f"^{shape}$")))
    return made


@dataclass
class Allowance:
    operations: frozenset[str]
    cases: frozenset[str]

    @classmethod
    def of(cls, given: Mapping) -> Allowance:
        return cls(frozenset(given.get("operations") or ()), frozenset(given.get("cases") or ()))

    def takes(self, route: Route | None) -> bool:
        if route is None or route.tag not in tools.SIDES or route.operation in tools.ROUND_OPERATIONS:
            return True
        return route.operation in self.operations

    def takes_case(self, case) -> bool:
        return EVERY_CASE in self.cases or case in self.cases


class Relay:
    def __init__(self, upstream: str, token: str, run_key: str, play: Mapping,
                 report: Callable[[str], None] = lambda text: None, clock: Callable[[], float] = time.monotonic,
                 schema: dict | None = None):
        self.upstream = upstream.rstrip("/")
        self.token = token
        self.run_key = run_key
        self.pace = Pace.of(play["pace"])
        self.allowance = Allowance.of(play["allowance"])
        self.report = report
        self.clock = clock
        self.routes = routes(schema if schema is not None else tools.contract())
        self.recent: list[float] = []
        self.lock = threading.Lock()
        self.server: ThreadingHTTPServer | None = None

    def route_of(self, method: str, path: str) -> Route | None:
        return next((route for route in self.routes if route.method == method.upper() and route.pattern.match(path)),
                    None)

    def signed(self, authorization: str | None) -> bool:
        return hmac.compare_digest((authorization or "").encode(), f"Bearer {self.run_key}".encode())

    def decide(self, method: str, path: str, body: bytes) -> Refusal | None:
        route = self.route_of(method, path)
        name = route.operation if route else None
        if not self.allowance.takes(route):
            return self.refused(Refusal(403, NOT_AT_THIS_STEP, {"operation": name}), method, path)
        if name == CASE_FIRING and not self.allowance.takes_case(case_of(body)):
            return self.refused(Refusal(403, NOT_AT_THIS_STEP, {"case": case_of(body)}), method, path)
        if not counted(method, name):
            return None
        with self.lock:
            now = self.clock()
            wait = pace_wait(now, self.recent, self.pace)
            if wait is None:
                self.recent.append(now)
                return None
        return self.refused(Refusal(429, PACE_LIMITED, {"retry_after_s": round(wait, 1)}), method, path)

    def refused(self, refusal: Refusal, method: str, path: str) -> Refusal:
        self.report(f"{refusal.code} {method} {path} {json.dumps(refusal.params, sort_keys=True)}")
        return refusal

    def forward(self, method: str, target: str, body: bytes, content_type: str | None) -> requests.Response:
        headers = {"Authorization": f"Bearer {self.token}"}
        if content_type:
            headers["Content-Type"] = content_type
        return requests.request(method, self.upstream + target, data=body or None, headers=headers,
                                timeout=UPSTREAM_SECONDS, allow_redirects=False)

    def handler(self) -> type[BaseHTTPRequestHandler]:
        relay = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, status: int, content: bytes, headers: Mapping[str, str]):
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def refuse(self, refusal: Refusal):
                extra = {"Retry-After": str(int(refusal.params["retry_after_s"]) + 1)} \
                    if refusal.code == PACE_LIMITED else {}
                self.send(refusal.status, refusal.body(), {"Content-Type": "application/json", **extra})

            def answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                if not relay.signed(self.headers.get("Authorization")):
                    self.refuse(Refusal(401, NOT_SIGNED_IN))
                    return
                refusal = relay.decide(self.command, urlsplit(self.path).path, body)
                if refusal is not None:
                    self.refuse(refusal)
                    return
                try:
                    answered = relay.forward(self.command, self.path, body, self.headers.get("Content-Type"))
                except requests.RequestException:
                    self.send(502, Refusal(502, "unavailable").body(), {"Content-Type": "application/json"})
                    return
                kept = {key: answered.headers[key] for key in PASSED_HEADERS if key in answered.headers}
                self.send(answered.status_code, answered.content, kept)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = answer

        return Handler

    def start(self) -> str:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()


def case_of(body: bytes):
    try:
        given = json.loads(body or b"{}")
    except ValueError:
        return None
    return given.get("case") if isinstance(given, dict) else None
