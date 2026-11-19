from __future__ import annotations

import enum
import importlib
import inspect
import json
import types
import typing
from dataclasses import dataclass

import httpx2

from bots import signin, tools

HP_HEADERS = ("X-Origin", "X-Origin-HP")
LONGEST_TEXT = 20000


@dataclass(frozen=True)
class Seat:
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
    return arguments


def candidates(annotation) -> tuple:
    if isinstance(annotation, types.UnionType) or typing.get_origin(annotation) is typing.Union:
        return typing.get_args(annotation)
    return (annotation,)


def converted(value, annotation):
    for kind in candidates(annotation):
        if isinstance(kind, type) and issubclass(kind, enum.Enum):
            return kind(value)
        if isinstance(value, dict) and callable(getattr(kind, "from_dict", None)):
            return kind.from_dict(value)
    return value


def endpoint(operation: tools.Operation):
    return importlib.import_module(f"bots.client.api.{operation.tag}.{operation.name}")


def keyword_arguments(operation: tools.Operation, function, seat: Seat, arguments: dict) -> dict:
    parameters = inspect.signature(function).parameters
    given = {}
    if tools.ROUND_PARAMETER in parameters:
        given[tools.ROUND_PARAMETER] = seat.round_id
    for key in (*operation.path_parameters, *operation.query_parameters):
        if key in arguments:
            given[key] = converted(arguments[key], parameters[key].annotation)
    fields = {key: arguments[key] for key in operation.body_fields if key in arguments}
    if "body" in parameters and (fields or operation.body_required):
        given["body"] = converted(fields, parameters["body"].annotation)
    return given


def answer_body(response: httpx2.Response):
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text[:LONGEST_TEXT]


def outcome_of(name: str, response: httpx2.Response) -> dict:
    told = {"operation": name, "ok": response.is_success, "status": response.status_code,
            "body": answer_body(response)}
    headers = {key: response.headers[key] for key in HP_HEADERS if key in response.headers}
    if headers:
        told["headers"] = headers
    return told


def client_for(seat: Seat):
    client = signin.seated(seat.base_url, seat.token)
    answered: list[httpx2.Response] = []
    http = client.get_httpx_client()
    http.event_hooks["response"] = [*http.event_hooks.get("response", []), answered.append]
    return client, answered


def call(seat: Seat, name: str, arguments=None, client_and_answers=None) -> dict:
    try:
        if name not in tools.names_for(seat.side, tools.contract()):
            raise Refused("unknown_tool", "name", f"the {seat.side} seat has no tool {name!r}")
        operation, spec = tools.build(name, tools.contract())
        arguments = checked_arguments(spec, arguments)
        function = endpoint(operation).sync_detailed
        try:
            given = keyword_arguments(operation, function, seat, arguments)
        except (ValueError, KeyError, TypeError) as wrong:
            raise Refused("invalid", "", f"{name}: {wrong}") from wrong
    except Refused as refused:
        return refused.outcome(name)
    client, answered = client_and_answers or client_for(seat)
    answered.clear()
    try:
        function(client=client, **given)
    except httpx2.HTTPError as unreachable:
        return Refused("unreachable", "", f"{seat.base_url} did not answer: {unreachable}").outcome(name)
    except (ValueError, KeyError, TypeError):
        if not answered:
            raise
    return outcome_of(name, answered[-1])


def printed(outcome: dict) -> str:
    return json.dumps(outcome, indent=2, ensure_ascii=False)
