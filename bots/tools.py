from __future__ import annotations

import copy
import json
import os
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
STEP_OPERATIONS_VARIABLE = "CR_BOT_OPERATIONS"
WITHHELD_PARAMETERS = {"round_score": frozenset({"correlation"})}

DESCRIPTIONS = {
    "round_read": "Read the round: phase (created, starting, running, ended), matchup, players, allocation id, start, "
                  "deadline and end reason.",
    "round_events": "Read the round's event feed after a cursor. Pass the previous answer's `next` as `after` to "
                    "get only new events; you see only the kinds your side may see.",
    "round_topology": "Read the learner map of the range as your side may see it.",
    "round_score": "Read the score once the round has ended: objectives lost and kept, per-case outcomes "
                   "(one declared case is one decision however many alerts it drew) and free actions by origin. "
                   "Refused with round_running while the round runs. `pending` is true until the platform has "
                   "waited for late alerts and judged the round once more; read again until it is false.",
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
    "defence_ids_rules": "Read the rule file the Suricata sensor runs now, the last recorded IDS version and "
                         "whether the file is that version (a file edited in the IDS terminal and not reloaded is "
                         "not).",
    "defence_ids_versions": "List the recorded Suricata rule versions: each one's hash, whether it came from the "
                            "round's setup or a reload in the IDS terminal, and whether it was the tested text.",
    "defence_ids_test": "Test Suricata rule text against the recorded probes, never the live range. Answers "
                        "with per-case tp/fn/fp/tn, corroboration and totals. It passes only when no benign case "
                        "alerts and the sensor accepts the rules; only a file a passing test named can be "
                        "reloaded. Only one test runs at a time.",
    "defence_ids_test_result": "Read a stored Suricata rule test by its id.",
    "defence_waf": "Read the WAF files the defence edits (the CRS setup file, the request and response "
                   "exclusion files, the nginx files for deny and limit_req) as they are now, their hash, the "
                   "last recorded version and whether the files are that version.",
    "defence_waf_versions": "List the recorded WAF versions: each one's hash, whether it came from the round's "
                            "setup, the console or a reload in the terminal, and whether it was the tested set.",
    "defence_waf_version": "Read one recorded WAF version with the text of every file.",
    "defence_ids_version": "Read one recorded Suricata rule version with its text.",
    "defence_waf_check": "Check WAF files with nginx -t on a scratch copy without applying them; `files` maps a "
                         "file path to its whole text and leaves out the files you keep. Errors name the file "
                         "and line.",
    "defence_waf_test": "Test WAF files against the recorded probes, never the live range. Tool cases are "
                        "listed as untested. It passes only when no benign case is refused and nginx accepts the "
                        "files; only files a passing test named can be applied or reloaded. Only one test runs at "
                        "a time.",
    "defence_waf_test_result": "Read a stored WAF test by its id.",
    "defence_waf_apply": "Write WAF files, run nginx -t and reload, rolling back if nginx refuses them. "
                         "`base_version` must be the version you read. Refused with not_tested unless a passing "
                         "defence_waf_test of this round named the same files.",
    "defence_terminal": "Get a short-lived shell on the WAF as analyst: a web terminal URL and an SSH jump grant. "
                        "The WAF files are writable there, with sudo nginx -t and an nginx reload; the reload "
                        "loads only files a passing defence_waf_test named, and is recorded as the next WAF "
                        "version on the next request.",
    "defence_ids_terminal": "Get a short-lived shell on the Suricata sensor's host as analyst: a web terminal URL and "
                            "an SSH jump grant. The rule file is writable there, with the rule test and the rule "
                            "reload under sudo; the reload loads only a file a passing defence_ids_test named, and "
                            "is recorded as the next IDS version on the next request.",
    "defence_forfeit": "Give up the round as the defender. Ends the round.",
}


SHELL = "shell"
IDS_SHELL = "ids_shell"
LONGEST_SHELL_SECONDS = 600
SHELL_TERMINALS = {"attack": {SHELL: "attack_terminal"},
                   "defence": {SHELL: "defence_terminal", IDS_SHELL: "defence_ids_terminal"}}
SHELL_DESCRIPTIONS = {
    ("attack", SHELL): "Run one shell command on the attacker box as the learner, over the same SSH grant a human "
                       "attacker's terminal uses (attack_terminal). Each call is a new login, so cd and variables do "
                       "not carry over. Traffic from the shell can spend an origin like any other.",
    ("defence", SHELL): "Run one shell command on the WAF as analyst, over the same SSH grant a human defender's "
                        "terminal uses (defence_terminal). Each call is a new login, so cd and variables do not carry "
                        "over. The WAF files are writable there, with sudo nginx -t, sudo nginx -T and sudo systemctl "
                        "reload nginx; the reload loads only files a passing defence_waf_test named, and is recorded "
                        "as the next WAF version on the next request.",
    ("defence", IDS_SHELL): "Run one shell command on the Suricata sensor's host as analyst, over the same SSH grant "
                            "a human defender's IDS terminal uses (defence_ids_terminal). Each call is a new login. "
                            "The rule file is writable there and the eve log readable; `sudo -l` lists the rule test "
                            "and the rule reload you may run. The reload loads only a file a passing defence_ids_test "
                            "named and refuses one that turns off the sensor's logging; a reload is recorded as the "
                            "next IDS version on the next request.",
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
    in_round: bool


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


def step_operations() -> frozenset[str] | None:
    given = os.environ.get(STEP_OPERATIONS_VARIABLE)
    return None if given is None else frozenset(name for name in given.split(",") if name)


def names_for(side: str, schema: dict) -> list[str]:
    if side not in SIDES:
        raise ValueError(f"side must be one of {SIDES}, not {side!r}")
    entries = operation_entries(schema)
    given = step_operations()
    own = [name for name, (_, _, operation) in entries.items()
           if side_of(operation) == side and name not in HUMAN_ONLY and (given is None or name in given)]
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
    in_round = False
    for parameter in operation.get("parameters", []):
        key, where = parameter["name"], parameter["in"]
        if key == ROUND_PARAMETER:
            in_round = True
            continue
        if key in withheld:
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
                      body_fields=tuple(body.get("properties", {})), body_required=body_required,
                      in_round=in_round)
    return shape, spec


def terminal_of(side: str, tool: str = SHELL) -> str:
    return SHELL_TERMINALS[side][tool]


def shells(side: str, schema: dict) -> list[str]:
    granted = names_for(side, schema)
    return [tool for tool, terminal in SHELL_TERMINALS[side].items() if terminal in granted]


def has_shell(side: str, schema: dict, tool: str = SHELL) -> bool:
    return tool in shells(side, schema)


def shell_spec(side: str, tool: str = SHELL) -> dict:
    return {"name": tool, "description": SHELL_DESCRIPTIONS[(side, tool)], "input_schema": {
        "type": "object", "additionalProperties": False, "required": ["command"],
        "properties": {
            "command": {"type": "string", "minLength": 1, "description": "the command line, run by the login shell"},
            "timeout": {"type": "integer", "minimum": 1, "maximum": LONGEST_SHELL_SECONDS,
                        "description": "seconds before the command is stopped (default 120)"},
        }}}


def offered(side: str, schema: dict | None = None) -> list[str]:
    schema = schema if schema is not None else contract()
    return names_for(side, schema) + shells(side, schema)


def operations(side: str, schema: dict | None = None) -> dict[str, Operation]:
    schema = schema if schema is not None else contract()
    return {name: build(name, schema)[0] for name in names_for(side, schema)}


def specs(side: str, schema: dict | None = None) -> list[dict]:
    schema = schema if schema is not None else contract()
    built = [build(name, schema)[1] for name in names_for(side, schema)]
    return built + [shell_spec(side, tool) for tool in shells(side, schema)]


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in SIDES:
        print(f"usage: python -m bots.tools {{{'|'.join(SIDES)}}}", file=sys.stderr)
        return 2
    print(json.dumps(specs(argv[0]), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
