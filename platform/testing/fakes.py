from __future__ import annotations

import base64
import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from cr.config import WAF_FILES
from sandbox import crs, suricata
from sandbox.crs import READ_FILES, WRITE_FILE
from sandbox.runner import Ran, RangeUnavailable, decoded

SID = re.compile(r"sid\s*:\s*(\d+)")
OK = Ran(exit_code=0, output="")


@dataclass
class Sent:
    argv: list[str]
    stdin: str | None
    timeout: float

    @property
    def text(self) -> str:
        return " ".join(self.argv)


@dataclass
class FakeRunner:
    answers: list[tuple[str, str, int]] = field(default_factory=list)
    sent: list[Sent] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def answer(self, matching: str, output: str = "", exit_code: int = 0) -> "FakeRunner":
        self.answers.insert(0, (matching, output, exit_code))
        return self

    def __call__(self, argv: list[str], stdin: str | None = None, timeout: float = 60.0) -> Ran:
        one = Sent(list(argv), stdin, timeout)
        with self.lock:
            self.sent.append(one)
            output, code = next(((said, code) for matching, said, code in self.answers if matching in one.text),
                                ("", 0))
        return Ran(exit_code=code, output=decoded(output.encode()))

    def texts(self) -> list[str]:
        return [one.text for one in self.sent]

    def matching(self, part: str) -> list[Sent]:
        return [one for one in self.sent if part in one.text]


@dataclass
class FakeLauncher:
    runner: FakeRunner = field(default_factory=FakeRunner)
    images: list[str] = field(default_factory=list)

    def __call__(self, image: str, argv: list[str], timeout: float = 600.0) -> Ran:
        self.images.append(image)
        return self.runner(argv, timeout=timeout)


@dataclass
class FakeResponse:
    status_code: int = 200
    body: dict = field(default_factory=dict)
    text: str = ""

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> dict:
        return self.body


@dataclass
class FakeElastic:
    documents: list[dict] = field(default_factory=list)
    posted: list[tuple[str, dict]] = field(default_factory=list)
    put: list[tuple[str, bytes]] = field(default_factory=list)
    put_status: int = 200

    def add(self, doc_id: str, source: dict) -> "FakeElastic":
        self.documents.append({"_id": doc_id, "_source": source, "sort": [source.get("@timestamp")]})
        return self

    def post(self, url: str, json=None, timeout: float = 0.0) -> FakeResponse:
        self.posted.append((url, json))
        query = (json or {}).get("query") or {}
        hits = [hit for hit in sorted(self.documents, key=lambda hit: hit["sort"][0] or "")
                if _matches(hit, query)]
        return FakeResponse(body={"hits": {"hits": hits[:int((json or {}).get("size") or 10)]}})

    def put_pipeline(self, url: str, data: bytes = b"", timeout: float = 0.0, headers=None) -> FakeResponse:
        self.put.append((url, data))
        return FakeResponse(status_code=self.put_status)


def _matches(hit: dict, query: dict) -> bool:
    clauses = (query.get("bool") or {})
    for clause in clauses.get("filter") or ():
        if "term" in clause:
            [(name, wanted)] = clause["term"].items()
            if _field(hit["_source"], name) != wanted:
                return False
        if "range" in clause:
            [(name, bounds)] = clause["range"].items()
            if "gte" in bounds and str(_field(hit["_source"], name) or "") < str(bounds["gte"]):
                return False
    for clause in clauses.get("must_not") or ():
        if "ids" in clause and hit["_id"] in clause["ids"]["values"]:
            return False
    return True


def _field(source: dict, dotted: str):
    held = source
    for part in dotted.split("."):
        if not isinstance(held, dict):
            return None
        held = held.get(part)
    return held


def eve(*alerts: dict) -> str:
    return "\n".join(json.dumps({"event_type": "alert", **alert}) for alert in alerts) + "\n"


@dataclass
class FakeTarget:
    runners: dict[str, FakeRunner] = field(default_factory=dict)
    reached: list[str] = field(default_factory=list)

    def __call__(self, role: str) -> FakeRunner:
        self.reached.append(role)
        if role not in self.runners:
            raise RangeUnavailable(f"no role {role!r} on the fake target")
        return self.runners[role]


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
    loaded: str = ""
    snapshot: str | None = None
    snapshot_at: float = 1_800_000_000.0

    def edited(self, text: str, reloaded: bool) -> None:
        self.rules = text
        if reloaded:
            self.loaded = self.snapshot = text
            self.snapshot_at += 1

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
            if self.reload_fails:
                return Ran(1, "refused")
            self.loaded = self.rules
            return Ran(0, '{"return":"OK"}')
        return OK


@dataclass
class SensorNode(Recorded):
    fires: dict[str, dict[str, str]] = field(default_factory=dict)
    candidate: str = ""
    during: Callable[[], None] | None = None
    sensor: Sensor | None = None
    staged: set[str] = field(default_factory=set)

    def __call__(self, argv, stdin=None, timeout=60.0) -> Ran:
        one = self.note(argv, stdin, timeout)
        if argv[:3] == ["sh", "-c", suricata.READ_SNAPSHOT]:
            if self.sensor is None or self.sensor.snapshot is None:
                return Ran(1, "cat: /var/lib/cr-reloaded/ids/at: No such file or directory")
            return Ran(0, f"{self.sensor.snapshot_at:.9f}\n{self.sensor.snapshot}")
        if "candidate.rules" in one.text and stdin is not None:
            self.candidate = stdin
            return OK
        if argv[:2] == ["test", "-f"]:
            return OK if argv[2] in self.staged else Ran(1, "")
        unpacked = re.search(r"tar -x -C (\S+) && touch (\S+)", one.text)
        if unpacked:
            self.staged.add(unpacked[2])
            return OK
        replayed = re.search(r"sh /scratch/replay\.sh ((?:[A-Za-z0-9_.-]+ ?)+)", one.text)
        if replayed:
            if self.during is not None:
                self.during()
            sids = set(SID.findall(self.candidate))
            lines = []
            for case in replayed[1].split()[::2]:
                lines.append(f"{suricata.CASE_HEAD}{case}")
                lines += [json.dumps({"event_type": "alert", "alert": {"signature_id": int(sid), "signature": signature}})
                          for sid, signature in self.fires.get(case, {}).items() if sid in sids]
            return Ran(0, "\n".join(lines))
        return OK


LAID_CONFIG = re.compile(r"^printf %s (\S*) \| base64 -d > \S+/probes\.curl$", re.M)
CONFIG_LINE = re.compile(r'^(header|url) = "(.*)"$', re.M)


def replayed_requests(script: str) -> list[tuple[str, str]]:
    found = LAID_CONFIG.search(script)
    config = base64.b64decode(found[1]).decode() if found else ""
    made = []
    for segment in filter(None, config.split("\nnext\n")):
        lines = [(name, value.replace('\\"', '"').replace("\\\\", "\\"))
                 for name, value in CONFIG_LINE.findall(segment)]
        marker = next(value.split(": ", 1)[1] for name, value in lines
                      if name == "header" and value.startswith("X-Request-ID: "))
        made.append((marker, next(value for name, value in lines if name == "url")))
    return made


@dataclass
class Gateway(Recorded):
    files: dict[str, str] = field(default_factory=lambda: {path: "" for path in WAF_FILES})
    blocks: dict[str, str] = field(default_factory=dict)
    refused_paths: tuple[str, ...] = ()
    nginx_errors: str = ""
    reload_fails: str = ""
    workers: int = 1
    probes: list[dict] = field(default_factory=list)
    snapshot: dict[str, str] | None = None
    snapshot_at: float = 1_800_000_000.0

    def edited(self, path: str, text: str, reloaded: bool) -> None:
        self.files[path] = text
        if reloaded:
            self.workers += 1
            self.snapshot = dict(self.files)
            self.snapshot_at += 1

    def answered(self, marker: str, url: str) -> int:
        return 403 if marker in self.blocks or any(path in url for path in self.refused_paths) else 200

    def __call__(self, argv, stdin=None, timeout=60.0) -> Ran:
        one = self.note(argv, stdin, timeout)
        text = one.text
        if "replay.sh" in text:
            return Ran(0, "".join(f"{crs.REPLAYED_TAG} {at} {self.answered(marker, url)}\n"
                                  for at, (marker, url) in enumerate(replayed_requests(stdin or ""))))
        if argv[:3] == ["sh", "-c", READ_FILES]:
            return Ran(0, "".join(base64.b64encode(self.files.get(path, "").encode()).decode() + "\n"
                                  for path in argv[4:]))
        if argv[:3] == ["sh", "-c", crs.READ_SNAPSHOT]:
            if self.snapshot is None:
                return Ran(1, "cat: /var/lib/cr-reloaded/waf/at: No such file or directory")
            return Ran(0, f"{self.snapshot_at:.9f}\n" + "".join(
                base64.b64encode(self.snapshot.get(path, "").encode()).decode() + "\n" for path in argv[5:]))
        if argv[:3] == ["sh", "-c", WRITE_FILE]:
            if argv[4] in self.files:
                self.files[argv[4]] = stdin or ""
            return OK
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
        if "nginx -s reload" in text:
            if self.reload_fails:
                return Ran(1, f"nginx: [emerg] {self.reload_fails} in /etc/nginx/defence/http.conf:2")
            self.workers += 1
            return OK
        if "/proc/[0-9]*" in text:
            return Ran(0, str(self.workers))
        return OK


BOARD_TRUTH = {"admin": "pbkdf2_sha256$placeholder-admin", "jiwoo": "pbkdf2_sha256$placeholder-jiwoo"}


def board_runner(truth: dict) -> FakeRunner:
    return FakeRunner().answer("/internal/auth-users", json.dumps(truth))


def corp_runner(state: dict[str, str], binlog: str = "") -> FakeRunner:
    runner = FakeRunner().answer("mysqlbinlog", binlog)
    for table, rows in state.items():
        runner.answer(table, rows)
    return runner
