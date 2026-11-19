import importlib
import io
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from bots import calls, cli, play, tools
from bots.provider import ProviderNotFound, ToolCall, Turn, load

REPO = Path(__file__).resolve().parents[2]
TOKEN = "seat-token-placeholder"
ROUND = 7
HP = {"origin": {"id": "o1", "label": "first", "ip": "198.51.100.10"}, "left": 29, "budget": 30,
      "origins_left": 2, "spent": [],
      "rule": {"budget": 30, "per_request": 1, "refused_x": 3, "burst_per_s": 5, "burst_x": 2,
               "refused_statuses": [400, 403]}}
TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class FakePlatform:
    def __init__(self):
        self.answers = {}
        self.seen = []
        platform = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def answer(self):
                split = urlsplit(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                platform.seen.append({"method": self.command, "path": split.path, "query": parse_qs(split.query),
                                      "authorization": self.headers.get("Authorization"),
                                      "body": json.loads(raw) if raw else None})
                status, body, headers = platform.answers.get((self.command, split.path),
                                                             (404, {"errors": [{"path": "", "code": "not_found"}]},
                                                              {}))
                content = body if isinstance(body, bytes) else (b"" if body is None else json.dumps(body).encode())
                self.send_response(status)
                kind = "text/html" if isinstance(body, bytes) else "application/json"
                for key, value in {"Content-Type": kind, **headers}.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            do_GET = do_POST = do_DELETE = do_PUT = answer

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def on(self, method, path, status=200, body=None, headers=None):
        self.answers[(method, path)] = (status, body, headers or {})


@pytest.fixture
def platform():
    fake = FakePlatform()
    fake.thread.start()
    yield fake
    fake.server.shutdown()
    fake.server.server_close()


def attack_seat(platform):
    return calls.Seat(base_url=platform.url, token=TOKEN, round_id=ROUND, side="attack")


def environment(platform):
    return {cli.TOKEN_VARIABLE: TOKEN, cli.PLATFORM_VARIABLE: platform.url, cli.ROUND_VARIABLE: str(ROUND)}


def run_cli(argv, platform=None, stdin="", env=None):
    out = io.StringIO()
    code = cli.main(argv, stdin=io.StringIO(stdin), out=out,
                    environment=env if env is not None else (environment(platform) if platform else {}))
    return code, out.getvalue()


def all_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from all_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from all_keys(item)


def side_tagged(side):
    return {name for name, (_, _, operation) in tools.operation_entries(tools.contract()).items()
            if tools.side_of(operation) == side}


@pytest.mark.parametrize("side", tools.SIDES)
def test_a_side_gets_its_own_operations_and_the_round_reads_and_nothing_of_the_other_side(side):
    names = [spec["name"] for spec in tools.specs(side)]
    other = next(name for name in tools.SIDES if name != side)

    assert set(names) == (side_tagged(side) - tools.HUMAN_ONLY) | set(tools.ROUND_OPERATIONS)
    assert not set(names) & side_tagged(other)
    assert "defence_kibana" not in names
    assert len(names) == len(set(names))


@pytest.mark.parametrize("side", tools.SIDES)
def test_every_tool_spec_is_plain_json_schema_a_model_can_take(side):
    for spec in tools.specs(side):
        schema = spec["input_schema"]
        assert TOOL_NAME.match(spec["name"]), spec["name"]
        assert spec["description"], f"{spec['name']} has no description"
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert not {"$ref", "nullable"} & set(all_keys(schema)), spec["name"]
        assert tools.ROUND_PARAMETER not in schema["properties"], "the CLI fills the round in itself"
        assert set(schema.get("required", [])) <= set(schema["properties"])
        json.dumps(spec)


def test_every_described_operation_exists_and_every_side_operation_is_described_or_human_only():
    entries = tools.operation_entries(tools.contract())
    offered = {name for side in tools.SIDES for name in tools.names_for(side, tools.contract())}

    assert set(tools.DESCRIPTIONS) <= set(entries)
    assert offered == set(tools.DESCRIPTIONS)
    assert tools.HUMAN_ONLY <= set(entries)


def test_the_staff_only_correlation_switch_is_withheld_from_the_score_tool():
    score = next(spec for spec in tools.specs("attack") if spec["name"] == "round_score")

    assert "correlation" not in score["input_schema"]["properties"]


def test_a_nullable_field_becomes_a_null_type_and_a_body_flattens_beside_the_parameters():
    send = tools.build("attack_send", tools.contract())[1]["input_schema"]
    output = tools.build("attack_tool_output", tools.contract())[1]["input_schema"]

    assert send["properties"]["host"]["type"] == ["string", "null"]
    assert set(send["required"]) == {"method", "path"}
    assert set(output["properties"]) == {"after", "run_id"} and output["required"] == ["run_id"]


def test_a_body_field_clashing_with_a_parameter_is_refused():
    schema = json.loads(json.dumps(tools.contract()))
    operation = schema["paths"]["/api/rounds/{round_id}/attack/tools/{run_id}/"]["get"]
    operation["requestBody"] = {"required": True, "content": {"application/json": {
        "schema": {"type": "object", "properties": {"run_id": {"type": "integer"}}}}}}

    with pytest.raises(tools.SchemaMismatch, match="run_id"):
        tools.build("attack_tool_output", schema)


@pytest.mark.parametrize("side", tools.SIDES)
def test_every_tool_has_its_operation_in_the_generated_client(side):
    for name, operation in tools.operations(side).items():
        module = importlib.import_module(f"bots.client.api.{operation.tag}.{name}")
        assert callable(module.sync_detailed), name


def test_the_tools_command_prints_the_specs_and_needs_no_seat():
    code, printed = run_cli(["tools", "--side", "defence"])

    assert code == 0
    assert json.loads(printed) == tools.specs("defence")


def test_a_call_on_stdin_goes_out_with_the_seat_token_and_prints_the_answer_with_its_hp(platform):
    path = f"/api/rounds/{ROUND}/attack/requests/"
    platform.on("POST", path, body={"action": 3, "marker": "m-3", "status": 200, "headers": [], "body": "ok",
                                    "truncated": False, "hp": HP},
                headers={"X-Origin": "198.51.100.10", "X-Origin-HP": "29/30"})
    asked = {"name": "attack_send", "arguments": {"method": "GET", "path": "/search", "query": {"q": "x"}}}

    code, printed = run_cli(["call", "--side", "attack"], platform, stdin=json.dumps(asked))

    told = json.loads(printed)
    assert code == 0
    assert told["ok"] is True and told["status"] == 200 and told["body"]["hp"] == HP
    assert told["headers"] == {"X-Origin": "198.51.100.10", "X-Origin-HP": "29/30"}
    assert platform.seen == [{"method": "POST", "path": path, "query": {}, "authorization": f"Bearer {TOKEN}",
                              "body": {"method": "GET", "path": "/search", "query": {"q": "x"}}}]


def test_the_one_line_form_names_the_tool_and_infers_the_side(platform):
    path = f"/api/rounds/{ROUND}/defence/alerts/"
    platform.on("GET", path, body={"alerts": [], "next": 0})

    code, printed = run_cli(["defence_alerts", "--json", '{"engine": "ids", "after": 4, "src": "198.51.100.10"}'],
                            platform)

    assert code == 0 and json.loads(printed)["body"] == {"alerts": [], "next": 0}
    assert platform.seen[0]["query"] == {"engine": ["ids"], "after": ["4"], "src": ["198.51.100.10"]}


def test_path_parameters_and_an_empty_answer_reach_the_right_route(platform):
    path = f"/api/rounds/{ROUND}/attack/tools/12/"
    platform.on("DELETE", path, status=204)

    code, printed = run_cli(["attack_stop_tool", "--json", '{"run_id": 12}'], platform)

    assert code == 0
    assert json.loads(printed) == {"operation": "attack_stop_tool", "ok": True, "status": 204, "body": None}
    assert platform.seen[0]["method"] == "DELETE" and platform.seen[0]["path"] == path


def test_a_refusal_is_printed_with_its_code_and_hp_and_is_not_a_cli_failure(platform):
    refusal = {"errors": [{"path": "", "code": "origins_spent"}], "hp": {**HP, "left": 0, "origins_left": 0}}
    platform.on("POST", f"/api/rounds/{ROUND}/attack/cases/", status=409, body=refusal)

    code, printed = run_cli(["attack_fire_case", "--json", '{"case": "board-sqli-search"}'], platform)

    told = json.loads(printed)
    assert code == 0
    assert told["ok"] is False and told["status"] == 409 and told["body"] == refusal


def test_an_answer_that_is_not_json_is_still_reported(platform):
    platform.on("GET", f"/api/rounds/{ROUND}/attack/state/", status=502, body=b"<html>bad gateway</html>")

    code, printed = run_cli(["attack_state"], platform)

    told = json.loads(printed)
    assert code == 0
    assert told["status"] == 502 and "bad gateway" in told["body"]


def test_a_tool_of_the_other_side_is_refused_locally_and_nothing_is_sent(platform):
    asked = {"name": "defence_waf", "arguments": {}}

    code, printed = run_cli(["call", "--side", "attack"], platform, stdin=json.dumps(asked))

    told = json.loads(printed)
    assert code == cli.USAGE_ERROR
    assert told["local"] is True and told["errors"][0]["code"] == "unknown_tool"
    assert platform.seen == []


@pytest.mark.parametrize("arguments, code", [({"case": "x", "bogus": 1}, "unknown_field"), ({}, "required"),
                                             ([1], "invalid")])
def test_arguments_outside_the_tool_spec_are_refused_locally(platform, arguments, code):
    told = calls.call(attack_seat(platform), "attack_fire_case", arguments)

    assert told["local"] is True and told["errors"][0]["code"] == code
    assert platform.seen == []


def test_a_value_the_client_cannot_take_is_refused_locally(platform):
    told = calls.call(attack_seat(platform), "attack_send", {"method": "BREW", "path": "/"})

    assert told["local"] is True and told["errors"][0]["code"] == "invalid"
    assert platform.seen == []


def test_an_unreachable_platform_is_its_own_exit_code():
    env = {cli.TOKEN_VARIABLE: TOKEN, cli.PLATFORM_VARIABLE: "http://127.0.0.1:9", cli.ROUND_VARIABLE: "1"}

    code, printed = run_cli(["attack_state"], env=env)

    assert code == cli.UNREACHABLE and json.loads(printed)["errors"][0]["code"] == "unreachable"


def test_a_call_without_a_seat_token_says_what_to_set(capsys):
    code, printed = run_cli(["attack_state", "--round", "3", "--base-url", "http://127.0.0.1:9"], env={})

    assert code == cli.USAGE_ERROR and printed == ""
    assert cli.TOKEN_VARIABLE in capsys.readouterr().err


def test_an_unknown_tool_name_is_a_usage_error(platform, capsys):
    code, _ = run_cli(["attack_everything"], platform)

    assert code == cli.USAGE_ERROR and "attack_everything" in capsys.readouterr().err
    assert platform.seen == []


def test_the_attacker_prompt_tells_the_hit_point_rule_and_how_to_switch_origin():
    prompt = play.system_prompt("attack")

    for named in ("per_request", "refused_x", "burst_per_s", "burst_x", "refused_statuses", "origins_left",
                  "X-Origin-HP", "attack_next_origin", "origins/next/", "origins_spent"):
        assert named in prompt, named


def test_the_claude_code_prompt_adds_the_cli_and_the_loop_prompt_leaves_it_out():
    assert "python -m bots.cli" in play.system_prompt("defence", driving_the_cli=True)
    assert "python -m bots.cli" not in play.system_prompt("defence")
    code, printed = run_cli(["prompt", "--side", "attack"])
    assert code == 0 and "bots.cli call" in printed


def test_every_tool_and_code_the_prompts_and_readme_name_exists():
    schemas = tools.contract()["components"]["schemas"]
    codes = set(schemas["ErrorCodeEnum"]["enum"])
    not_codes = {*schemas["FieldError"]["properties"], "local", "hp", "base_version"}
    names = {spec["name"] for side in tools.SIDES for spec in tools.specs(side)}
    texts = [*(REPO / "bots" / "prompts").glob("*.md"), REPO / "bots" / "README.md"]

    for text in texts:
        quoted = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", text.read_text()))
        tool_like = {word for word in quoted if word.startswith(("attack_", "defence_", "round_", "lease_"))}
        unknown_tools = tool_like - names - codes
        assert not unknown_tools, f"{text.name}: {sorted(unknown_tools)}"
        errors_section = text.read_text().partition("## Errors")[2]
        named_codes = set(re.findall(r"`([a-z]+(?:_[a-z]+)*)`", errors_section)) - not_codes
        assert named_codes <= codes, f"{text.name}: {sorted(named_codes - codes)}"


SIDE_CODES = {
    "attacker.md": {"not_seated", "invalid", "unknown_case", "unknown_tool", "unknown_run", "round_not_started",
                    "round_closed", "origins_spent", "attacker_unavailable", "range_unavailable"},
    "defender.md": {"invalid", "suricata_syntax", "crs_refused", "apply_refused", "unread_sid", "stale_version",
                    "test_busy", "round_not_started", "round_closed", "sensor_unavailable", "waf_unavailable",
                    "elastic_unavailable"},
}


def errors_named(path: Path) -> set[str]:
    return set(re.findall(r"`([a-z]+(?:_[a-z]+)*)`", path.read_text().partition("## Errors")[2]))


@pytest.mark.parametrize("prompt", sorted(SIDE_CODES))
def test_each_side_prompt_and_the_readme_name_every_error_code_the_design_gives_that_side(prompt):
    codes = SIDE_CODES[prompt]

    assert codes - errors_named(REPO / "bots" / "prompts" / prompt) == set()
    assert codes - errors_named(REPO / "bots" / "README.md") == set()


class Scripted:
    def __init__(self, turns):
        self.turns = list(turns)
        self.seen = []

    def turn(self, system, tool_specs, transcript):
        self.seen.append({"system": system, "tools": [spec["name"] for spec in tool_specs],
                          "transcript": list(transcript)})
        return self.turns.pop(0) if self.turns else Turn(text="done")


def scripted_attacker():
    return Scripted([
        Turn(text="looking", calls=(ToolCall("c1", "attack_next_origin", {}),)),
        Turn(text="peeking", calls=(ToolCall("c2", "defence_alerts", {}),)),
    ])


def test_a_provider_plays_the_seat_with_the_side_prompt_and_tools_until_it_stops(platform):
    platform.on("GET", f"/api/rounds/{ROUND}/attack/state/", body={"phase": "running", "hp": HP})
    platform.on("POST", f"/api/rounds/{ROUND}/attack/origins/next/", body={"origin": "o2", "hp": HP})
    scripted = scripted_attacker()

    played = play.play(attack_seat(platform), scripted, turns=10)

    assert played.reason == "finished" and played.turns == 3
    assert scripted.seen[0]["system"] == play.system_prompt("attack")
    assert scripted.seen[0]["tools"] == [spec["name"] for spec in tools.specs("attack")]
    assert '"phase": "running"' in scripted.seen[0]["transcript"][0]["text"]
    results = [entry["result"] for entry in played.transcript if entry["role"] == "tool"]
    assert results[0]["status"] == 200 and results[0]["body"]["origin"] == "o2"
    assert results[1]["local"] is True and results[1]["errors"][0]["code"] == "unknown_tool"
    assert [seen["path"] for seen in platform.seen] == [f"/api/rounds/{ROUND}/attack/state/",
                                                        f"/api/rounds/{ROUND}/attack/origins/next/"]


def test_a_provider_that_never_stops_runs_out_of_turns(platform):
    platform.on("GET", f"/api/rounds/{ROUND}/attack/state/", body={"phase": "running", "hp": HP})
    endless = Scripted([Turn(calls=(ToolCall(str(n), "attack_state", {}),)) for n in range(5)])

    played = play.play(attack_seat(platform), endless, turns=2)

    assert played.reason == "out_of_turns" and played.turns == 2


def test_the_run_command_loads_the_provider_by_name_and_reports_each_step_as_a_json_line(platform):
    platform.on("GET", f"/api/rounds/{ROUND}/attack/state/", body={"phase": "running", "hp": HP})
    platform.on("POST", f"/api/rounds/{ROUND}/attack/origins/next/", body={"origin": "o2", "hp": HP})

    code, printed = run_cli(["run", "--side", "attack", "--provider", "tests.test_bots:scripted_attacker"],
                            platform)

    lines = [json.loads(line) for line in printed.splitlines()]
    assert code == 0
    assert lines[0]["role"] == "user" and lines[-1] == {"role": "end", "reason": "finished", "turns": 3}


@pytest.mark.parametrize("reference", ["no_colon", "tests.no_such_module:x", "tests.test_bots:ROUND",
                                       "tests.test_bots:attack_seat_without_turn"])
def test_a_provider_reference_that_does_not_give_a_provider_is_refused(reference):
    with pytest.raises(ProviderNotFound):
        load(reference)


def attack_seat_without_turn():
    return object()
