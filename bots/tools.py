from __future__ import annotations

import copy
import json
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "openapi" / "schema.yaml"
SIDES = ("attack", "defence")
ROUND_PARAMETER = "round_id"
REFERENCE = "#/components/schemas/"
METHODS = ("get", "post", "put", "patch", "delete")

ROUND_OPERATIONS = ("round_read", "round_events", "round_topology", "round_score", "allocation_heartbeat")
HUMAN_ONLY = frozenset({"defence_kibana"})
WITHHELD_PARAMETERS = {"round_score": frozenset({"correlation"})}

DESCRIPTIONS = {
    "round_read": "Read the round: phase (created, starting, running, ended), matchup, players, allocation id, start, "
                  "deadline and end reason.",
    "round_events": "Read the round's event feed after a cursor. Pass the previous answer's `next` as `after` to "
                    "get only new events; you see only the kinds your side may see.",
    "round_topology": "Read the learner map of the range as your side may see it.",
    "round_score": "Read the score once the round has ended: objectives lost and kept, per-case outcomes "
                   "(one declared case is one decision however many alerts it drew) and free actions by origin. "
                   "Refused with round_running while the round runs.",
    "allocation_heartbeat": "Keep the round's allocation alive; `allocation_id` is the `allocation` field of round_read.",
    "attack_state": "Read the attack player's state: phase, brief, target hosts, objectives (kept or lost), "
                    "every origin with when and why it was spent, and the remaining block.",
    "attack_cases": "List the declared attack cases you may fire: case id, kind (http or tool), malicious, title.",
    "attack_fire_case": "Fire one declared case by id. An http case is sent at once; a tool case starts a tool "
                        "run you then read with attack_tool_output. One declared case counts as one decision.",
    "attack_send": "Send one free HTTP request to the target from the attacker box through the current origin. "
                   "`path` is the request path, `host` picks one of the target's hosts, `query` and `headers` are "
                   "string maps, `body` is the raw body. Answers with the target's status, headers and body.",
    "attack_tools": "List the tools you may run with their argument schemas, and the runs you started.",
    "attack_start_tool": "Start a tool run on the attacker box with `tool` and its `args`. Runs asynchronously; "
                         "read its output with attack_tool_output.",
    "attack_tool_output": "Read a tool run's output from byte offset `after`; pass the previous answer's "
                          "`offset` to read only new output. `done` and `exit_code` tell when it finished.",
    "attack_stop_tool": "Stop a running tool run.",
    "attack_loot": "Submit a value you took from the target. The target decides whether it matches the secret; "
                   "the answer says whether an objective was lost and never reveals the secret.",
    "attack_next_origin": "Give up the current origin now (it is marked spent) and move to the next unspent one. "
                          "Use it when the defence has started refusing it.",
    "attack_terminal": "Get a short-lived shell on the attacker box: a web terminal URL and an SSH jump grant. "
                       "Traffic from the shell can spend an origin like any other: the WAF's error log is read when the next API call for the round comes in.",
    "attack_forfeit": "Give up the round as the attacker. Ends the round.",
    "defence_state": "Read the defence player's state: phase, brief, target hosts, objectives with whether you saw "
                     "each one go, the applied IDS and WAF versions, and the alert count.",
    "defence_alerts": "Read alerts after a cursor, optionally filtered by `engine` (ids or waf), `rule` and `src` "
                      "(source IP). Pass the previous answer's `next` as `after`.",
    "defence_traffic": "Read the requests the WAF saw per source IP: requests, refused, last seen. Pass the "
                       "previous answer's `next` as `after`.",
    "defence_probes": "List the round's probe set the rule test replays: case, malicious, recorded, tool case.",
    "defence_ids_rules": "Read the applied Suricata rule text and its version.",
    "defence_ids_versions": "List the applied Suricata rule versions and whether each was the tested text.",
    "defence_ids_check": "Check Suricata rule text for syntax on every sensor without applying it.",
    "defence_ids_test": "Test Suricata rule text against the recorded probes, never the live range. Answers "
                        "with per-case tp/fn/fp/tn, corroboration and totals. Only one test runs at a time.",
    "defence_ids_test_result": "Read a stored Suricata rule test by its id.",
    "defence_ids_apply": "Apply Suricata rule text to every sensor. `base_version` must be the version you read; "
                         "a stale one is refused with stale_version. Pass `tested` with the test id of the same "
                         "text to record that it was tested.",
    "defence_ids_disabled": "List the Suricata rules disabled for a while.",
    "defence_ids_disable": "Disable one Suricata rule by `sid` for `minutes`, with a `reason`.",
    "defence_ids_enable": "Enable a disabled Suricata rule again by `sid`.",
    "defence_waf": "Read the applied CRS posture (paranoia, exclusions, thresholds, detection_only) and its "
                   "version.",
    "defence_waf_versions": "List the applied CRS posture versions and whether each was the tested posture.",
    "defence_waf_check": "Check a CRS posture without applying it; errors come back by field path.",
    "defence_waf_test": "Test a CRS posture against the recorded probes, never the live range. Tool cases are "
                        "listed as untested. Only one test runs at a time.",
    "defence_waf_test_result": "Read a stored CRS posture test by its id.",
    "defence_waf_apply": "Apply a CRS posture. `base_version` must be the version you read; pass `tested` with "
                         "the test id of the same posture to record that it was tested.",
    "defence_terminal": "Get a short-lived read-only shell on the WAF: a web terminal URL and an SSH jump grant.",
    "defence_forfeit": "Give up the round as the defender. Ends the round.",
}


@dataclass(frozen=True)
class Operation:
    name: str
    tag: str
    method: str
    path: str
    path_parameters: tuple[str, ...]
    query_parameters: tuple[str, ...]
    body_fields: tuple[str, ...]
    body_required: bool


class SchemaMismatch(RuntimeError):
    pass


@cache
def contract(path: Path = SCHEMA) -> dict:
    return yaml.safe_load(path.read_text())


def side_of(operation: dict) -> str | None:
    tags = operation.get("tags") or []
    return tags[0] if tags else None


def operation_entries(schema: dict) -> dict[str, tuple[str, str, dict]]:
    found = {}
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            if method in METHODS:
                found[operation["operationId"]] = (method, path, operation)
    return found


def names_for(side: str, schema: dict) -> list[str]:
    if side not in SIDES:
        raise ValueError(f"side must be one of {SIDES}, not {side!r}")
    entries = operation_entries(schema)
    own = [name for name, (_, _, operation) in entries.items()
           if side_of(operation) == side and name not in HUMAN_ONLY]
    return [name for name in ROUND_OPERATIONS if name in entries] + sorted(own)


def resolved(node, components: dict, seen: tuple[str, ...] = ()):
    if isinstance(node, list):
        return [resolved(item, components, seen) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        name = node["$ref"].removeprefix(REFERENCE)
        if name in seen:
            raise SchemaMismatch(f"recursive schema {name}")
        return resolved(copy.deepcopy(components[name]), components, (*seen, name))
    plain = {key: resolved(value, components, seen) for key, value in node.items() if key != "nullable"}
    if node.get("nullable"):
        return nullable(plain)
    return plain


def nullable(schema: dict) -> dict:
    kind = schema.get("type")
    if isinstance(kind, str):
        widened = {**schema, "type": [kind, "null"]}
        if "enum" in widened:
            widened["enum"] = [*widened["enum"], None]
        return widened
    if set(schema) == {"allOf"} and len(schema["allOf"]) == 1:
        return {"anyOf": [schema["allOf"][0], {"type": "null"}]}
    return {"anyOf": [schema, {"type": "null"}]}


def body_schema(operation: dict, components: dict) -> tuple[dict, bool]:
    body = operation.get("requestBody")
    if not body:
        return {}, False
    schema = body.get("content", {}).get("application/json", {}).get("schema")
    if schema is None:
        raise SchemaMismatch(f"{operation['operationId']} takes a body that is not JSON")
    return resolved(schema, components), bool(body.get("required"))


def described(schema: dict, parameter: dict) -> dict:
    text = parameter.get("description")
    if text and "description" not in schema and not schema.get("enum"):
        return {**schema, "description": text}
    return schema


def build(name: str, schema: dict) -> tuple[Operation, dict]:
    entries = operation_entries(schema)
    if name not in entries:
        raise SchemaMismatch(f"{name} is not an operation of {SCHEMA.name}")
    method, path, operation = entries[name]
    components = schema["components"]["schemas"]
    withheld = WITHHELD_PARAMETERS.get(name, frozenset())
    properties, required = {}, []
    path_parameters, query_parameters = [], []
    for parameter in operation.get("parameters", []):
        key, where = parameter["name"], parameter["in"]
        if key == ROUND_PARAMETER or key in withheld:
            continue
        properties[key] = described(resolved(parameter.get("schema", {}), components), parameter)
        if parameter.get("required"):
            required.append(key)
        (path_parameters if where == "path" else query_parameters).append(key)
    body, body_required = body_schema(operation, components)
    clashing = set(body.get("properties", {})) & set(properties)
    if clashing:
        raise SchemaMismatch(f"{name}: body fields {sorted(clashing)} clash with its parameters")
    properties.update(body.get("properties", {}))
    if body_required:
        required.extend(body.get("required", []))
    input_schema = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        input_schema["required"] = required
    spec = {"name": name, "description": DESCRIPTIONS.get(name, ""), "input_schema": input_schema}
    shape = Operation(name=name, tag=side_of(operation), method=method, path=path,
                      path_parameters=tuple(path_parameters), query_parameters=tuple(query_parameters),
                      body_fields=tuple(body.get("properties", {})), body_required=body_required)
    return shape, spec


def operations(side: str, schema: dict | None = None) -> dict[str, Operation]:
    schema = schema if schema is not None else contract()
    return {name: build(name, schema)[0] for name in names_for(side, schema)}


def specs(side: str, schema: dict | None = None) -> list[dict]:
    schema = schema if schema is not None else contract()
    return [build(name, schema)[1] for name in names_for(side, schema)]


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in SIDES:
        print(f"usage: python -m bots.tools {{{'|'.join(SIDES)}}}", file=sys.stderr)
        return 2
    print(json.dumps(specs(argv[0]), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
