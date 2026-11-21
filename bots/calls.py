from __future__ import annotations

import json
from dataclasses import dataclass

import requests

from bots import rest, shell, signin, tools

ORIGIN_HEADERS = ("X-Origin", "X-Origins-Left")
LONGEST_TEXT = 20000


@dataclass(frozen=True)
class Player:
    base_url: str
    token: str
    round_id: int
    side: str


class Refused(ValueError):
    def __init__(self, code: str, path: str, message: str):
        super().__init__(message)
        self.code = code
        self.path = path

    def outcome(self, name: str) -> dict:
        return {"operation": name, "ok": False, "status": None, "local": True,
                "errors": [{"path": self.path, "code": self.code, "message": str(self)}]}


def of_type(value, kind: str) -> bool:
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    expected = {"string": str, "boolean": bool, "object": dict, "array": list, "null": type(None)}.get(kind)
    return expected is None or isinstance(value, expected)


def fits(value, schema: dict) -> bool:
    if "anyOf" in schema:
        return any(fits(value, option) for option in schema["anyOf"])
    if "allOf" in schema:
        return all(fits(value, part) for part in schema["allOf"])
    if "enum" in schema and value not in schema["enum"]:
        return False
    kinds = schema.get("type")
    if kinds is None:
        return True
    return any(of_type(value, kind) for kind in (kinds if isinstance(kinds, list) else [kinds]))


def checked_arguments(spec: dict, arguments) -> dict:
    if arguments is None:
        return {}
    if not isinstance(arguments, dict):
        raise Refused("invalid", "", "arguments must be a JSON object")
    schema = spec["input_schema"]
    unknown = sorted(set(arguments) - set(schema["properties"]))
    if unknown:
        raise Refused("unknown_field", unknown[0], f"{spec['name']} takes no {', '.join(unknown)}")
    missing = [key for key in schema.get("required", []) if key not in arguments]
    if missing:
        raise Refused("required", missing[0], f"{spec['name']} needs {', '.join(missing)}")
    wrong = [key for key, value in arguments.items() if not fits(value, schema["properties"][key])]
    if wrong:
        raise Refused("invalid", wrong[0], f"{spec['name']}: {wrong[0]} does not fit its schema")
    return arguments


def answer_body(response: requests.Response):
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text[:LONGEST_TEXT]


def outcome_of(name: str, response: requests.Response) -> dict:
    told = {"operation": name, "ok": response.ok, "status": response.status_code, "body": answer_body(response)}
    headers = {key: response.headers[key] for key in ORIGIN_HEADERS if key in response.headers}
    if headers:
        told["headers"] = headers
    return told


def session_for(player: Player) -> signin.Platform:
    return signin.playing(player.base_url, player.token)


def sent(operation: tools.Operation, player: Player, session: signin.Platform, arguments: dict):
    named = {key: arguments[key] for key in (*operation.path_parameters, *operation.query_parameters)
             if key in arguments}
    if operation.in_round:
        named[tools.ROUND_PARAMETER] = player.round_id
    fields = {key: arguments[key] for key in operation.body_fields if key in arguments}
    body = fields if fields or operation.body_required else None
    return rest.request(session, operation.name, body=body, **named)


def spec_of(player: Player, name: str) -> tuple[tools.Operation | None, dict]:
    if name not in tools.offered(player.side):
        raise Refused("unknown_tool", "name", f"the {player.side} player has no tool {name!r}")
    if name == tools.SHELL:
        return None, tools.shell_spec(player.side)
    return tools.build(name, tools.contract())


def call(player: Player, name: str, arguments=None, session: signin.Platform | None = None) -> dict:
    try:
        operation, spec = spec_of(player, name)
        arguments = checked_arguments(spec, arguments)
    except Refused as refused:
        return refused.outcome(name)
    session = session or session_for(player)
    if operation is None:
        return shell.run(player, arguments, lambda: call(player, tools.terminal_of(player.side), {}, session))
    try:
        return outcome_of(name, sent(operation, player, session, arguments))
    except requests.RequestException as unreachable:
        return Refused("unreachable", "", f"{player.base_url} did not answer: {unreachable}").outcome(name)


def printed(outcome: dict) -> str:
    return json.dumps(outcome, indent=2, ensure_ascii=False)
