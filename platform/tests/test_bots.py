import io
import subprocess
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from bots import calls, cli, launcher, play, rest, shell, tools
from bots.pace import Pace, counted, pace_wait
from bots.relay import Relay
from bots.provider import ProviderNotFound, ToolCall, Turn, load

REPO = Path(__file__).resolve().parents[2]
TOKEN = "player-token-placeholder"
ROUND = 7
REMAINING = {"origin": {"id": "o1", "label": "first", "ip": "198.51.100.10"}, "left": 2, "total": 3,
             "spent": ["198.51.100.9"]}
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


def attack_player(platform):
    return calls.Player(base_url=platform.url, token=TOKEN, round_id=ROUND, side="attack")


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

    assert set(names) == (side_tagged(side) - tools.HUMAN_ONLY) | set(tools.ROUND_OPERATIONS) | set(tools.SHELL_TERMINALS[side])
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


class Recording:
    def __init__(self):
        self.sent = []

    def request(self, method, url, params=None, json=None):
        self.sent.append((method, url, params, json))


@pytest.mark.parametrize("side", tools.SIDES)
def test_every_api_tool_is_sent_to_its_route_from_the_schema_alone(side):
    for name, operation in tools.operations(side).items():
        session = Recording()
        named = {key: 5 for key in operation.path_parameters}
        if operation.in_round:
            named[tools.ROUND_PARAMETER] = ROUND
        rest.request(session, name, **named)
        method, url, _, _ = session.sent[0]
        assert method == operation.method.upper() and "{" not in url, name


def test_a_schema_request_fills_the_path_encodes_the_query_and_refuses_what_the_operation_does_not_take():
    session = Recording()

    rest.request(session, "round_list", state="open", mine=True)
    rest.request(session, "staff_probes_record", wargame_id="a b")

    assert session.sent == [("GET", "/api/rounds/", {"state": "open", "mine": "true"}, None),
                            ("POST", "/api/staff/wargames/a%20b/probes/record/", {}, None)]
    with pytest.raises(TypeError, match="bogus"):
        rest.request(session, "round_list", bogus=1)
    with pytest.raises(TypeError, match="wargame_id"):
        rest.request(session, "staff_probes_record")
    with pytest.raises(rest.UnknownOperation):
        rest.request(session, "nothing_here")


def test_the_tools_command_prints_the_specs_and_needs_no_player():
    code, printed = run_cli(["tools", "--side", "defence"])

    assert code == 0
    assert json.loads(printed) == tools.specs("defence")


def test_a_call_on_stdin_goes_out_with_the_player_token_and_prints_the_answer_with_its_origin_headers(platform):
    path = f"/api/rounds/{ROUND}/attack/requests/"
    platform.on("POST", path, body={"action": 3, "marker": "m-3", "status": 200, "headers": [], "body": "ok",
                                    "truncated": False, "remaining": REMAINING},
                headers={"X-Origin": "198.51.100.10", "X-Origins-Left": "2"})
    asked = {"name": "attack_send", "arguments": {"method": "GET", "path": "/search", "query": {"q": "x"}}}

    code, printed = run_cli(["call", "--side", "attack"], platform, stdin=json.dumps(asked))

    told = json.loads(printed)
    assert code == 0
    assert told["ok"] is True and told["status"] == 200 and told["body"]["remaining"] == REMAINING
    assert told["headers"] == {"X-Origin": "198.51.100.10", "X-Origins-Left": "2"}
    assert platform.seen == [{"method": "POST", "path": path, "query": {}, "authorization": f"Bearer {TOKEN}",
                              "body": {"method": "GET", "path": "/search", "query": {"q": "x"}}}]


def test_the_one_line_form_names_the_tool_and_infers_the_side(platform):
    path = f"/api/rounds/{ROUND}/defence/alerts/"
    platform.on("GET", path, body={"alerts": [], "next": 0})

    code, printed = run_cli(["defence_alerts", "--json", '{"engine": "ids", "after": 4, "src": "198.51.100.10"}'],
                            platform)

    assert code == 0 and json.loads(printed)["body"] == {"alerts": [], "next": 0}
    assert platform.seen[0]["query"] == {"engine": ["ids"], "after": ["4"], "src": ["198.51.100.10"]}


def test_arguments_read_from_a_file_go_out_with_both_quote_kinds_as_written(platform, tmp_path):
    platform.on("POST", f"/api/rounds/{ROUND}/attack/requests/", body={"action": 3, "status": 200})
    written = tmp_path / "call.json"
    written.write_text('{"method": "GET", "path": "/search", "query": {"q": "x\' ORDER BY \\"a\\"-- -"}}')

    code, _ = run_cli(["attack_send", "--json-file", str(written)], platform)

    assert code == 0 and platform.seen[0]["body"]["query"] == {"q": 'x\' ORDER BY "a"-- -'}


def test_path_parameters_and_an_empty_answer_reach_the_right_route(platform):
    path = f"/api/rounds/{ROUND}/attack/tools/12/"
    platform.on("DELETE", path, status=204)

    code, printed = run_cli(["attack_stop_tool", "--json", '{"run_id": 12}'], platform)

    assert code == 0
    assert json.loads(printed) == {"operation": "attack_stop_tool", "ok": True, "status": 204, "body": None}
    assert platform.seen[0]["method"] == "DELETE" and platform.seen[0]["path"] == path


def test_a_refusal_is_printed_with_its_code_and_is_not_a_cli_failure(platform):
    refusal = {"errors": [{"path": "", "code": "origins_spent"}]}
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
    told = calls.call(attack_player(platform), "attack_fire_case", arguments)

    assert told["local"] is True and told["errors"][0]["code"] == code
    assert platform.seen == []


def test_a_value_the_schema_does_not_take_is_refused_locally(platform):
    for arguments in ({"method": "BREW", "path": "/"}, {"method": "GET", "path": 3}):
        told = calls.call(attack_player(platform), "attack_send", arguments)

        assert told["local"] is True and told["errors"][0]["code"] == "invalid", arguments
    assert platform.seen == []


def test_an_unreachable_platform_is_its_own_exit_code():
    env = {cli.TOKEN_VARIABLE: TOKEN, cli.PLATFORM_VARIABLE: "http://127.0.0.1:9", cli.ROUND_VARIABLE: "1"}

    code, printed = run_cli(["attack_state"], env=env)

    assert code == cli.UNREACHABLE and json.loads(printed)["errors"][0]["code"] == "unreachable"


def test_a_call_without_a_player_token_says_what_to_set(capsys):
    code, printed = run_cli(["attack_state", "--round", "3", "--base-url", "http://127.0.0.1:9"], env={})

    assert code == cli.USAGE_ERROR and printed == ""
    assert cli.TOKEN_VARIABLE in capsys.readouterr().err


def test_an_unknown_tool_name_is_a_usage_error(platform, capsys):
    code, _ = run_cli(["attack_everything"], platform)

    assert code == cli.USAGE_ERROR and "attack_everything" in capsys.readouterr().err
    assert platform.seen == []


def test_the_attacker_prompt_tells_how_an_origin_is_spent_and_how_to_switch_origin():
    prompt = play.system_prompt("attack")

    for named in ("deny", "limit_req", "403", "remaining", "X-Origins-Left", "attack_next_origin", "origins/next/",
                  "origins_spent"):
        assert named in prompt, named


def test_the_claude_code_prompt_adds_the_cli_and_the_loop_prompt_leaves_it_out():
    assert "python -m bots.cli" in play.system_prompt("defence", driving_the_cli=True)
    assert "python -m bots.cli" not in play.system_prompt("defence")
    code, printed = run_cli(["prompt", "--side", "attack"])
    assert code == 0 and "python -m bots.cli <tool> --json" in printed and "bots.cli call" not in printed


def test_every_tool_and_code_the_prompts_and_readme_name_exists():
    schemas = tools.contract()["components"]["schemas"]
    codes = set(schemas["ErrorCodeEnum"]["enum"])
    not_codes = {*schemas["FieldError"]["properties"], "local", "base_version"}
    names = {spec["name"] for side in tools.SIDES for spec in tools.specs(side)}
    texts = [*(REPO / "bots" / "prompts").glob("*.md"), REPO / "bots" / "README.md"]

    for text in texts:
        quoted = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", text.read_text()))
        tool_like = {word for word in quoted if word.startswith(("attack_", "defence_", "round_", "allocation_"))}
        unknown_tools = tool_like - names - codes
        assert not unknown_tools, f"{text.name}: {sorted(unknown_tools)}"
        errors_section = text.read_text().partition("## Errors")[2]
        named_codes = set(re.findall(r"`([a-z]+(?:_[a-z]+)*)`", errors_section)) - not_codes
        assert named_codes <= codes, f"{text.name}: {sorted(named_codes - codes)}"


SIDE_CODES = {
    "attacker.md": {"not_a_player", "invalid", "unknown_case", "unknown_tool", "unknown_run", "round_not_started",
                    "round_closed", "origins_spent", "attacker_unavailable", "range_unavailable"},
    "defender.md": {"invalid", "suricata_syntax", "crs_refused", "apply_refused", "stale_version",
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


def test_a_provider_plays_the_player_with_the_side_prompt_and_tools_until_it_stops(platform):
    platform.on("GET", f"/api/rounds/{ROUND}/attack/state/", body={"phase": "running", "remaining": REMAINING})
    platform.on("POST", f"/api/rounds/{ROUND}/attack/origins/next/", body={"origin": "o2", "remaining": REMAINING})
    scripted = scripted_attacker()

    played = play.play(attack_player(platform), scripted, turns=10)

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
    platform.on("GET", f"/api/rounds/{ROUND}/attack/state/", body={"phase": "running", "remaining": REMAINING})
    endless = Scripted([Turn(calls=(ToolCall(str(n), "attack_state", {}),)) for n in range(5)])

    played = play.play(attack_player(platform), endless, turns=2)

    assert played.reason == "out_of_turns" and played.turns == 2


def test_the_run_command_loads_the_provider_by_name_and_reports_each_step_as_a_json_line(platform):
    platform.on("GET", f"/api/rounds/{ROUND}/attack/state/", body={"phase": "running", "remaining": REMAINING})
    platform.on("POST", f"/api/rounds/{ROUND}/attack/origins/next/", body={"origin": "o2", "remaining": REMAINING})

    code, printed = run_cli(["run", "--side", "attack", "--provider", "tests.test_bots:scripted_attacker"],
                            platform)

    lines = [json.loads(line) for line in printed.splitlines()]
    assert code == 0
    assert lines[0]["role"] == "user" and lines[-1] == {"role": "end", "reason": "finished", "turns": 3}


@pytest.mark.parametrize("reference", ["no_colon", "tests.no_such_module:x", "tests.test_bots:ROUND",
                                       "tests.test_bots:attack_player_without_turn"])
def test_a_provider_reference_that_does_not_give_a_provider_is_refused(reference):
    with pytest.raises(ProviderNotFound):
        load(reference)


def attack_player_without_turn():
    return object()


SSH_GRANT = {"host": "jump.example", "port": 2222, "user": "jump", "private_key": "-----KEY-----",
             "target_host": "10.20.0.5", "target_user": "analyst", "expires_at": "2026-11-21T10:00:00Z"}


def defence_player(platform):
    return calls.Player(base_url=platform.url, token=TOKEN, round_id=ROUND, side="defence")


@pytest.fixture
def ssh(monkeypatch):
    ran = []
    answers = []

    def fake_run(argv, **named):
        key = next(argv[index + 1] for index, word in enumerate(argv) if word == "-i")
        ran.append({"argv": argv, "key": Path(key).read_text(), "mode": Path(key).stat().st_mode & 0o777,
                    "timeout": named["timeout"]})
        answer = answers.pop(0) if answers else (0, "ok\n", "")
        if answer == "late":
            raise subprocess.TimeoutExpired(argv, named["timeout"], output=b"partial")
        return subprocess.CompletedProcess(argv, answer[0], answer[1], answer[2])

    monkeypatch.setattr(shell.subprocess, "run", fake_run)
    monkeypatch.setattr(shell, "OPEN", {})
    return ran, answers


def test_each_side_has_a_shell_tool_only_while_the_schema_grants_its_terminal():
    schema = json.loads(json.dumps(tools.contract()))
    del schema["paths"]["/api/rounds/{round_id}/defence/terminal/"]

    assert tools.shell_spec("defence") in tools.specs("defence")
    assert tools.SHELL in tools.offered("attack")
    assert tools.SHELL not in tools.offered("defence", schema)
    assert tools.SHELL not in [spec["name"] for spec in tools.specs("defence", schema)]


def test_the_defence_shell_opens_the_human_terminal_grant_once_and_runs_each_command_over_its_jump(platform, ssh):
    ran, _ = ssh
    platform.on("GET", f"/api/rounds/{ROUND}/defence/terminal/",
                body={"ws_url": f"/vm-terminal/defence/{ROUND}/", "ssh": SSH_GRANT})
    player = defence_player(platform)

    first = calls.call(player, "shell", {"command": "sudo nginx -t"})
    second = calls.call(player, "shell", {"command": "cat /etc/nginx/defence/http.conf", "timeout": 30})

    assert first == {"operation": "shell", "ok": True, "exit_code": 0, "stdout": "ok\n", "stderr": ""}
    assert second["ok"] is True
    assert [seen["path"] for seen in platform.seen] == [f"/api/rounds/{ROUND}/defence/terminal/"]
    assert platform.seen[0]["authorization"] == f"Bearer {TOKEN}"
    argv = ran[0]["argv"]
    assert argv[0] == "ssh" and argv[-2:] == ["analyst@10.20.0.5", "sudo nginx -t"]
    jump = next(word for word in argv if word.startswith("ProxyCommand="))
    assert "-p 2222 -W %h:%p jump@jump.example" in jump
    assert ran[0]["key"] == "-----KEY-----\n" and ran[0]["mode"] == 0o600
    assert [seen["timeout"] for seen in ran] == [shell.DEFAULT_SECONDS, 30]


def test_the_defence_ids_shell_opens_the_sensor_grant_apart_from_the_waf_one(platform, ssh):
    ran, _ = ssh
    platform.on("GET", f"/api/rounds/{ROUND}/defence/terminal/", body={"ssh": SSH_GRANT})
    platform.on("GET", f"/api/rounds/{ROUND}/defence/ids/terminal/",
                body={"ws_url": f"/vm-terminal/ids/{ROUND}/", "ssh": {**SSH_GRANT, "target_host": "10.20.0.9"}})
    player = defence_player(platform)

    ids = calls.call(player, "ids_shell", {"command": "sudo suricata -T"})
    calls.call(player, "shell", {"command": "sudo nginx -t"})
    calls.call(player, "ids_shell", {"command": "cat /var/log/suricata/eve.json"})

    assert ids == {"operation": "ids_shell", "ok": True, "exit_code": 0, "stdout": "ok\n", "stderr": ""}
    assert [seen["path"] for seen in platform.seen] == [f"/api/rounds/{ROUND}/defence/ids/terminal/",
                                                       f"/api/rounds/{ROUND}/defence/terminal/"]
    assert [one["argv"][-2] for one in ran] == ["analyst@10.20.0.9", "analyst@10.20.0.5", "analyst@10.20.0.9"]
    assert tools.shell_spec("defence", "ids_shell") in tools.specs("defence")
    assert "ids_shell" not in tools.offered("attack")


def test_an_ssh_failure_drops_the_grant_so_the_next_command_asks_for_a_new_one(platform, ssh):
    ran, answers = ssh
    answers.extend([(255, "", "Permission denied"), (0, "", "")])
    platform.on("GET", f"/api/rounds/{ROUND}/defence/terminal/", body={"ssh": SSH_GRANT})
    player = defence_player(platform)

    failed = calls.call(player, "shell", {"command": "id"})
    calls.call(player, "shell", {"command": "id"})

    assert failed["ok"] is False and failed["exit_code"] == 255 and "denied" in failed["stderr"]
    assert len(platform.seen) == 2 and len(ran) == 2


def test_a_refused_terminal_is_the_shell_answer_and_nothing_runs(platform, ssh):
    ran, _ = ssh
    refusal = {"errors": [{"path": "", "code": "round_not_started"}]}
    platform.on("GET", f"/api/rounds/{ROUND}/defence/terminal/", status=409, body=refusal)

    told = calls.call(defence_player(platform), "shell", {"command": "id"})

    assert told == {"operation": "shell", "ok": False, "status": 409, "body": refusal}
    assert ran == []


def test_a_command_that_outlasts_its_timeout_is_reported_with_what_it_printed(platform, ssh):
    _, answers = ssh
    answers.append("late")
    platform.on("GET", f"/api/rounds/{ROUND}/defence/terminal/", body={"ssh": SSH_GRANT})

    told = calls.call(defence_player(platform), "shell", {"command": "sleep 900", "timeout": 1})

    assert told["timed_out"] is True and told["exit_code"] is None and told["stdout"] == "partial"


@pytest.mark.parametrize("arguments", [{}, {"command": "id", "timeout": "soon"}, {"command": "id", "user": "root"}])
def test_shell_arguments_outside_its_spec_are_refused_locally(platform, ssh, arguments):
    told = calls.call(defence_player(platform), "shell", arguments)

    assert told["local"] is True
    assert platform.seen == [] and ssh[0] == []


def test_the_one_line_shell_needs_the_side_because_both_players_have_one(platform, capsys, ssh):
    code, _ = run_cli(["shell", "--json", '{"command": "id"}'], platform)

    assert code == cli.USAGE_ERROR and "--side" in capsys.readouterr().err
    assert platform.seen == []


STEP_PACE = {"per_window": 3, "window_s": 300, "min_gap_s": 15}


def test_pace_waits_for_the_window_and_the_gap():
    pace = Pace.of(STEP_PACE)

    assert pace_wait(100.0, [], pace) is None
    assert pace_wait(100.0, [90.0], pace) == 5.0
    assert pace_wait(400.0, [100.0, 200.0, 390.0], pace) == 5.0
    assert pace_wait(420.0, [150.0, 200.0, 390.0], pace) == 30.0
    assert pace_wait(451.0, [150.0, 200.0, 390.0], pace) is None


def test_pace_counts_every_write_and_delete_and_the_terminal_grants_but_no_other_read_no_forfeit_no_heartbeat():
    assert counted("POST", "attack_fire_case") and counted("DELETE", "attack_stop_tool")
    assert counted("GET", "attack_terminal") and counted("GET", "defence_terminal")
    assert counted("GET", "defence_ids_terminal")
    assert not counted("GET", "round_events") and not counted("GET", "defence_alerts")
    assert not counted("POST", "attack_forfeit") and not counted("POST", "allocation_heartbeat")


def attack_play(cases=("board-sqli-search",)):
    return {"pace": {"per_window": 10, "window_s": 300, "min_gap_s": 0},
            "allowance": {"operations": ["attack_state", "attack_fire_case", "attack_terminal"], "cases": list(cases)}}


@pytest.fixture
def relayed(platform):
    refused = []
    relay = Relay(platform.url, TOKEN, "run-key-placeholder", attack_play(), report=refused.append)
    url = relay.start()
    yield url, relay, refused
    relay.stop()


def through(url, method, path, key="run-key-placeholder", body=None):
    return requests.request(method, url + path, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=10)


def test_relay_refuses_an_operation_or_a_case_the_step_does_not_give_and_sends_nothing(platform, relayed):
    url, _, refused = relayed

    tools_asked = through(url, "GET", f"/api/rounds/{ROUND}/attack/tools/")
    case_asked = through(url, "POST", f"/api/rounds/{ROUND}/attack/cases/", body={"case": "board-sqli-orderby-sqlmap"})

    assert (tools_asked.status_code, case_asked.status_code) == (403, 403)
    assert {tools_asked.json()["errors"][0]["code"], case_asked.json()["errors"][0]["code"]} == {"not_at_this_step"}
    assert platform.seen == [] and len(refused) == 2


def test_relay_swaps_the_run_key_for_the_player_token_and_never_forwards_another_key(platform, relayed):
    url, _, _ = relayed
    platform.on("POST", f"/api/rounds/{ROUND}/attack/cases/", body={"fired": True}, headers={"X-Origin": "o1"})

    fired = through(url, "POST", f"/api/rounds/{ROUND}/attack/cases/", body={"case": "board-sqli-search"})
    stranger = through(url, "GET", f"/api/rounds/{ROUND}/attack/state/", key=TOKEN)

    assert fired.status_code == 200 and fired.json() == {"fired": True} and fired.headers["X-Origin"] == "o1"
    assert stranger.status_code == 401
    assert [(seen["path"], seen["authorization"], seen["body"]) for seen in platform.seen] == [
        (f"/api/rounds/{ROUND}/attack/cases/", f"Bearer {TOKEN}", {"case": "board-sqli-search"})]


def test_relay_answers_pace_limited_with_the_wait_once_the_step_s_pace_is_used(platform):
    platform.on("POST", f"/api/rounds/{ROUND}/attack/cases/", body={})
    play_once = {**attack_play(), "pace": {"per_window": 1, "window_s": 300, "min_gap_s": 0}}
    relay = Relay(platform.url, TOKEN, "k", play_once, clock=lambda: 1000.0)
    url = relay.start()
    try:
        first = through(url, "POST", f"/api/rounds/{ROUND}/attack/cases/", key="k", body={"case": "board-sqli-search"})
        second = through(url, "POST", f"/api/rounds/{ROUND}/attack/cases/", key="k", body={"case": "board-sqli-search"})
    finally:
        relay.stop()

    assert first.status_code == 200 and second.status_code == 429
    assert second.json()["errors"][0] == {"path": "", "code": "pace_limited", "params": {"retry_after_s": 300.0}}
    assert len(platform.seen) == 1


def claimed_run(side, stance=None):
    return {"run": 4, "round": ROUND, "side": side, "step": "1", "token": TOKEN, "model": "claude-haiku-5-5",
            "budget_usd": 2.0, "max_turns": 200, "pace": STEP_PACE,
            "allowance": {"operations": [f"{side}_state"], "cases": ["*"]},
            "card": None, "prompt": {"side": "attacker" if side == "attack" else "defender", "stance": stance}}


def test_launcher_command_runs_claude_code_on_bash_and_json_files_in_an_empty_directory_with_the_step_s_model():
    attack = claimed_run("attack", stance="Assigned technique for this engagement, as MITRE ATT&CK describes it (T1190 ...)")
    command = launcher.child_command(attack, "opening", "bot3")
    claude = command[command.index("claude"):]

    assert command[:3] == ["sudo", "-u", "bot3"] and "CR_PLAYER_TOKEN" in command[4] and TOKEN not in command
    assert claude[claude.index("--tools") + 1] == "Bash,Write" and claude[claude.index("--model") + 1] == "claude-haiku-5-5"
    assert "Edit(/*.json)" in claude[claude.index("--allowedTools"):claude.index("--disallowedTools")]
    assert claude[claude.index("--max-budget-usd") + 1] == "2.0" and claude[claude.index("--max-turns") + 1] == "200"
    assert "Bash(python -m bots.cli *)" in claude and "Bash(cat *)" in claude[claude.index("--disallowedTools"):]
    assert {"--safe-mode", "--strict-mcp-config", "--no-session-persistence"} <= set(claude)
    assert claude[claude.index("--setting-sources") + 1] == "" and claude[claude.index("--permission-mode") + 1] == "dontAsk"
    assert json.loads(claude[claude.index("--settings") + 1]) == {"bashOutputMaxChars": 128000}
    script = command[command.index("-c") + 1]
    assert 'mkdir -p "$HOME/run/work"' in script and 'cd "$HOME/run/work"' in script
    assert not any(str(REPO) in word or "redteam" in word for word in command)
    assert "MITRE ATT&CK" in launcher.system_text(attack) and "bots.cli" in launcher.system_text(attack)
    assert "MITRE ATT&CK" not in launcher.system_text(claimed_run("defence", stance="Assigned technique for this engagement"))


def test_the_attack_opening_is_the_engagement_brief_and_the_defence_opening_keeps_the_range_context():
    attack = launcher.opening_text(claimed_run("attack"), {"phase": "running"})
    defence = launcher.opening_text(claimed_run("defence"), {"phase": "running"})

    assert launcher.ENGAGEMENT in attack and launcher.RANGE_CONTEXT not in attack and "attack_state" in attack
    assert launcher.RANGE_CONTEXT in defence and launcher.ENGAGEMENT not in defence and "defence_state" in defence
    assert attack.endswith('{"phase": "running"}') and defence.endswith('{"phase": "running"}')


def test_the_launcher_profile_is_the_prompt_hashes_and_the_claude_code_version_and_moves_when_a_prompt_does(
        tmp_path, monkeypatch):
    monkeypatch.setattr(play, "PROMPTS", tmp_path)
    (tmp_path / "attacker.md").write_text("first")
    environment = {launcher.CLAUDE_CODE_VERSION_VARIABLE: "2.1.331"}

    before = launcher.launcher_profile(environment)
    (tmp_path / "attacker.md").write_text("second")

    assert before["claude_code"] == "2.1.331" and set(before["prompts"]) == {"attacker.md"}
    assert launcher.launcher_profile(environment)["prompts"] != before["prompts"]


def test_the_model_claude_code_started_on_is_a_note_of_the_run():
    transcript = launcher.Transcript(hidden=())

    transcript.take({"type": "system", "subtype": "init", "model": "claude-sonnet-5-5"})

    assert [(note["kind"], note["text"]) for note in transcript.taken()] == [("result", "model claude-sonnet-5-5")]


def test_a_safeguard_stop_and_a_fallback_to_another_model_are_counted_and_noted_with_both_models():
    transcript = launcher.Transcript(hidden=())

    transcript.take({"type": "system", "subtype": "informational", "level": "notice",
                     "content": "Opus 5.5's safeguards stopped the response above · continuing once with that noted"})
    transcript.take({"type": "system", "subtype": "model_refusal_fallback", "original_model": "claude-opus-5-5",
                     "fallback_model": "claude-opus-4-8", "api_refusal_category": "cyber",
                     "content": "Opus 4.8 is answering instead"})

    texts = [note["text"] for note in transcript.taken()]
    assert transcript.refusals == 2 and "safeguards stopped" in texts[0]
    assert texts[1] == "model_refusal_fallback claude-opus-5-5 -> claude-opus-4-8 [cyber]: Opus 4.8 is answering instead"


def test_notes_are_masked_of_the_player_token_the_run_key_and_any_anthropic_key():
    transcript = launcher.Transcript(hidden=(TOKEN, "run-key-placeholder", "", ""))

    transcript.take({"type": "assistant", "message": {"content": [
        {"type": "text", "text": f"token {TOKEN} key run-key-placeholder and sk-ant-oat01-AbC_123-x"},
        {"type": "tool_use", "name": "Bash", "input": {"command": f"python -m bots.cli attack_state # {TOKEN}"}}]}})
    transcript.take({"type": "result", "subtype": "success", "num_turns": 3, "total_cost_usd": 0.5,
                     "result": f"closing sk-ant-api03-zzz {TOKEN}"})

    texts = " ".join(note["text"] for note in transcript.taken())
    finished = transcript.finish(0, False)
    assert TOKEN not in texts and "run-key-placeholder" not in texts and "sk-ant-" not in texts
    assert finished == {"exit": "success", "cost_usd": 0.5, "turns": 3, "refusals": 0,
                        "closing": "closing [hidden] [hidden]"}
