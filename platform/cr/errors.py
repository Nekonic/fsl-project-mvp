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
    codes = frozenset({
        "invalid", "malformed", "required", "null", "blank", "max_length", "min_length", "max_value", "min_value",
        "invalid_choice", "not_a_list", "empty", "does_not_exist", "unknown_account", "username_taken", "password_too_short",
        "password_too_common", "password_entirely_numeric", "password_too_similar",
        "not_an_object", "not_a_choice", "not_a_text", "not_a_boolean", "not_a_text_list", "not_a_positive_integer",
        "unknown_field", "unknown_wargame",
        "unknown_objective", "unknown_profile", "matchup_not_allowed", "not_malicious",
        "not_recorded", "name_taken",
    })


class NotSignedIn(DomainError):
    code = "not_signed_in"
    status = 401
    codes = frozenset({"not_signed_in", "wrong_credentials"})


class NotAPlayer(DomainError):
    code = "not_a_player"
    status = 403
    codes = frozenset({"not_a_player", "not_staff", "csrf_failed", "account_pending", "not_operator"})


class NotFound(DomainError):
    code = "not_found"
    status = 404
    codes = frozenset({"not_found", "unknown_case", "unknown_tool", "unknown_run", "unknown_origin", "unknown_user",
                       "unknown_block", "unknown_round", "unknown_allocation", "unknown_problem", "unknown_posture"})


class NotAllowed(DomainError):
    code = "method_not_allowed"
    status = 405
    codes = frozenset({"method_not_allowed"})


class NotAcceptable(DomainError):
    code = "not_acceptable"
    status = 406
    codes = frozenset({"not_acceptable"})


class Conflict(DomainError):
    code = "conflict"
    status = 409
    codes = frozenset({
        "conflict", "round_not_started", "round_closed", "round_running", "origins_spent", "stale_version",
        "stale_revision", "test_busy", "already_playing", "player_taken", "in_use",
        "own_account", "loot_not_taken", "allocation_closed", "players_open", "objective_fallen", "round_started",
        "probe_running", "round_open", "range_not_cloud",
    })


class UnsupportedMedia(DomainError):
    code = "unsupported_media_type"
    status = 415
    codes = frozenset({"unsupported_media_type"})


class EngineRefused(DomainError):
    code = "engine_refused"
    status = 422
    codes = frozenset({"engine_refused", "suricata_syntax", "crs_refused", "apply_refused", "unread_sid"})


class TooMany(DomainError):
    code = "too_many"
    status = 429
    codes = frozenset({"too_many", "sign_in_blocked", "sign_ups_throttled"})


class ServerError(DomainError):
    code = "server_error"
    status = 500
    codes = frozenset({"server_error"})


class Unavailable(DomainError):
    code = "unavailable"
    status = 503
    codes = frozenset({
        "unavailable", "range_unavailable", "range_drifted", "attacker_unavailable", "sensor_unavailable",
        "waf_unavailable", "elastic_unavailable", "kibana_unavailable", "ground_truth_unavailable",
        "tool_unavailable", "sign_ups_closed",
    })


KINDS = (Invalid, NotSignedIn, NotAPlayer, NotFound, NotAllowed, NotAcceptable, Conflict, UnsupportedMedia,
         EngineRefused, TooMany, ServerError, Unavailable)
CODES = frozenset(code for kind in KINDS for code in kind.codes)
