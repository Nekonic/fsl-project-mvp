from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from range.runner import Ran
from testing.fakes import Sent

SID = re.compile(r"sid\s*:\s*(\d+)")
OK = Ran(exit_code=0, output="")


@dataclass
class Recorded:
    sent: list[Sent] = field(default_factory=list)

    def texts(self) -> list[str]:
        return [one.text for one in self.sent]

    def note(self, argv, stdin, timeout) -> Sent:
        one = Sent(list(argv), stdin, timeout)
        self.sent.append(one)
        return one


@dataclass
class Sensor(Recorded):
    rules: str = ""
    path: str = "/var/lib/suricata/rules/local.rules"
    syntax: dict[int, str] = field(default_factory=dict)
    reload_fails: bool = False

    def __call__(self, argv, stdin=None, timeout=60.0) -> Ran:
        one = self.note(argv, stdin, timeout)
        if argv[:2] == ["cat", self.path]:
            return Ran(0, self.rules)
        if "suricata -T" in one.text:
            wrong = [f"E: detect: error parsing signature at line {line}: {message}"
                     for line, message in self.syntax.items() if line <= len((stdin or "").splitlines())]
            return Ran(1, "\n".join(wrong)) if wrong else OK
        if f"cat > {self.path}" in one.text:
            self.rules = stdin or ""
            return OK
        if "reload-rules" in one.text:
            return Ran(1, "refused") if self.reload_fails else Ran(0, '{"return":"OK"}')
        return OK


@dataclass
class SensorNode(Recorded):
    fires: dict[str, dict[str, str]] = field(default_factory=dict)
    candidate: str = ""
    during: Callable[[], None] | None = None

    def __call__(self, argv, stdin=None, timeout=60.0) -> Ran:
        one = self.note(argv, stdin, timeout)
        if "candidate.rules" in one.text and stdin is not None:
            self.candidate = stdin
            return OK
        replayed = re.search(r"-r /pcaps/([A-Za-z0-9_-]+)\.pcap", one.text)
        if replayed:
            if self.during is not None:
                self.during()
            sids = set(SID.findall(self.candidate))
            alerts = [{"event_type": "alert", "alert": {"signature_id": int(sid), "signature": signature}}
                      for sid, signature in self.fires.get(replayed[1], {}).items() if sid in sids]
            return Ran(0, "\n".join(json.dumps(alert) for alert in alerts))
        return OK


@dataclass
class Gateway(Recorded):
    file: str = ""
    rules: str = "/etc/nginx/modsecurity/crs/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf"
    blocks: dict[str, str] = field(default_factory=dict)
    nginx_errors: str = ""
    workers: int = 1
    probes: list[dict] = field(default_factory=list)

    def __call__(self, argv, stdin=None, timeout=60.0) -> Ran:
        one = self.note(argv, stdin, timeout)
        text = one.text
        if argv[0] == "curl":
            marker = next(part.split(": ", 1)[1] for part in argv if part.startswith("X-Request-ID: "))
            return Ran(0, "403" if marker in self.blocks else "200")
        if "probe-upstream.py" in text:
            self.probes = json.loads(stdin or "[]")
            return OK
        if "audit.log" in text and text.startswith("sh -c cat"):
            return Ran(0, "\n".join(json.dumps({"transaction": {
                "request": {"headers": {"X-Request-ID": marker}},
                "messages": [{"message": signature, "details": {"ruleId": "942100"}}]}})
                for marker, signature in self.blocks.items()))
        if "nginx -t -p" in text:
            return Ran(1, f"nginx: [emerg] {self.nginx_errors} in /x.conf:3") if self.nginx_errors else OK
        if text == f"sh -c cat {self.rules} 2>/dev/null || true":
            return Ran(0, self.file)
        if text == f"sh -c cat > {self.rules}":
            self.file = stdin or ""
            return OK
        if "nginx -s reload" in text:
            self.workers += 1
            return OK
        if "/proc/[0-9]*" in text:
            return Ran(0, str(self.workers))
        return OK


@dataclass
class FakeRange:
    sensors: dict[str, Sensor] = field(default_factory=dict)
    nodes: dict[str, SensorNode] = field(default_factory=dict)
    gateway: Gateway = field(default_factory=Gateway)
    slots: list[int] = field(default_factory=list)

    def runner(self, role: str, segment_id: str = ""):
        if role == "gateway":
            return self.gateway
        return self.sensors.setdefault(role, Sensor())

    def node_runner(self, role: str):
        return self.nodes.setdefault(role, SensorNode())

    def in_slot(self, number: int) -> "FakeRange":
        self.slots.append(number)
        return self


HELD: dict[str, FakeRange] = {}


def connect(options, declared) -> FakeRange:
    return HELD["range"]
