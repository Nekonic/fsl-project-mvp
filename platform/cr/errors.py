from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FieldError:
    path: str
    code: str
    line: int | None = None
    params: dict[str, Any] = field(default_factory=dict)

    def shown(self) -> dict[str, Any]:
        found: dict[str, Any] = {"path": self.path, "code": self.code}
        if self.line is not None:
            found["line"] = self.line
        if self.params:
            found["params"] = dict(self.params)
        return found


class DomainError(Exception):
    code = "error"
    status = 500
    codes: frozenset[str] = frozenset()

    def __init__(self, message: str = "", *, code: str = "", path: str = "", line: int | None = None,
                 params: dict[str, Any] | None = None, errors: tuple[FieldError, ...] = ()):
        chosen = code or type(self).code
        super().__init__(message or chosen)
        self.code = chosen
        self.errors = tuple(errors) or (FieldError(path=path, code=chosen, line=line, params=dict(params or {})),)

    @property
    def params(self) -> dict[str, Any]:
        return dict(self.errors[0].params)

    def shown(self) -> dict[str, Any]:
        return {"errors": [error.shown() for error in self.errors]}


class Invalid(DomainError):
    code = "invalid"
    status = 400
    codes = frozenset({"invalid"})


class NotSignedIn(DomainError):
    code = "not_signed_in"
    status = 401
    codes = frozenset({"not_signed_in"})


class NotSeated(DomainError):
    code = "not_seated"
    status = 403
    codes = frozenset({"not_seated"})


class NotFound(DomainError):
    code = "not_found"
    status = 404
    codes = frozenset({"not_found", "unknown_case", "unknown_tool", "unknown_run", "unknown_origin"})


class Conflict(DomainError):
    code = "conflict"
    status = 409
    codes = frozenset({
        "conflict", "round_not_started", "round_closed", "round_running", "origins_spent", "stale_version",
        "stale_revision", "test_busy", "already_seated", "seat_taken", "in_use", "step_locked",
    })


class EngineRefused(DomainError):
    code = "engine_refused"
    status = 422
    codes = frozenset({"engine_refused", "suricata_syntax", "crs_refused", "apply_refused", "unread_sid"})


class Unavailable(DomainError):
    code = "unavailable"
    status = 503
    codes = frozenset({
        "unavailable", "range_unavailable", "range_drifted", "attacker_unavailable", "sensor_unavailable",
        "waf_unavailable", "elastic_unavailable", "kibana_unavailable", "ground_truth_unavailable",
        "tool_unavailable",
    })


KINDS = (Invalid, NotSignedIn, NotSeated, NotFound, Conflict, EngineRefused, Unavailable)
CODES = frozenset(code for kind in KINDS for code in kind.codes)
