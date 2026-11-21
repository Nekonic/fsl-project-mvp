from __future__ import annotations

from urllib.parse import quote

import requests

from bots import tools


class UnknownOperation(LookupError):
    pass


def query_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def request(session: requests.Session, operation_id: str, body=None, **named) -> requests.Response:
    entries = tools.operation_entries(tools.contract())
    if operation_id not in entries:
        raise UnknownOperation(f"{operation_id} is not an operation of {tools.SCHEMA.name}")
    method, path, operation = entries[operation_id]
    where = {parameter["name"]: parameter["in"] for parameter in operation.get("parameters", [])}
    unknown = sorted(set(named) - set(where))
    if unknown:
        raise TypeError(f"{operation_id} takes no {', '.join(unknown)}")
    in_path = {key for key, place in where.items() if place == "path"}
    missing = sorted(in_path - set(named))
    if missing:
        raise TypeError(f"{operation_id} needs {', '.join(missing)}")
    filled = path.format(**{key: quote(str(named[key]), safe="") for key in in_path})
    query = {key: query_value(value) for key, value in named.items()
             if where[key] == "query" and value is not None}
    return session.request(method.upper(), filled, params=query, json=body)
