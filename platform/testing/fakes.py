from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field

from range.runner import Ran


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
        return Ran(exit_code=code, output=output)

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
