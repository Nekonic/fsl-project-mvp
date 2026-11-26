from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

from bots import calls, play, provider, tools

TOKEN_VARIABLE = "CR_PLAYER_TOKEN"
PLATFORM_VARIABLE = "CR_PLATFORM_URL"
ROUND_VARIABLE = "CR_ROUND"
TESTS_DIR_VARIABLE = "CR_BOT_TESTS_DIR"
FINISH_TEST = "finish-test"
COMMANDS = ("tools", "prompt", "call", "run", FINISH_TEST)
TEST_RESULTS = {"defence_waf_test": "defence_waf_test_result", "defence_ids_test": "defence_ids_test_result"}
TEST_OF_RESULT = {result: test for test, result in TEST_RESULTS.items()}
USAGE_ERROR = 2
UNREACHABLE = 3


class Unusable(RuntimeError):
    pass


def side_argument(parser: argparse.ArgumentParser, required: bool = True) -> None:
    parser.add_argument("--side", choices=tools.SIDES, required=required)


def player_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--round", type=int, default=None, help=f"the round id (default: ${ROUND_VARIABLE})")
    parser.add_argument("--base-url", default=None, help=f"the platform's base URL (default: ${PLATFORM_VARIABLE})")


def parser() -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(
        prog="python -m bots.cli",
        description=f"Drive one player of a round through the attack or defence API. The player token is read from "
                    f"${TOKEN_VARIABLE}. Also: python -m bots.cli <tool> --json '{{...}}'.")
    commands = made.add_subparsers(dest="command", required=True)
    side_argument(commands.add_parser("tools", help="print the tool specs of a side as JSON"))
    prompt = commands.add_parser("prompt", help="print the system prompt of a side")
    side_argument(prompt)
    prompt.add_argument("--loop", action="store_true", help="the prompt a provider loop gets, without the CLI part")
    call = commands.add_parser("call", help="read {name, arguments} as JSON on stdin and make that one call")
    side_argument(call)
    player_arguments(call)
    run = commands.add_parser("run", help="let a provider play as the player until it stops or runs out of turns")
    side_argument(run)
    player_arguments(run)
    run.add_argument("--provider", required=True, help="package.module:factory returning a provider")
    run.add_argument("--turns", type=int, default=play.DEFAULT_TURNS)
    finish = commands.add_parser(FINISH_TEST, help="make the rule test a job file holds and store its answer there")
    finish.add_argument("job_file")
    return made


def operation_parser(name: str) -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(prog=f"python -m bots.cli {name}")
    side_argument(made, required=False)
    player_arguments(made)
    given = made.add_mutually_exclusive_group()
    given.add_argument("--json", default="{}", help="the tool's arguments as a JSON object")
    given.add_argument("--json-file", default=None, help="a file holding the tool's arguments as a JSON object")
    given.add_argument("--job", type=int, default=None,
                       help="with a rule test's result tool: read the rule test this CLI started as that job")
    return made


def arguments_text(arguments: argparse.Namespace) -> str:
    if arguments.json_file is None:
        return arguments.json
    try:
        return Path(arguments.json_file).read_text()
    except OSError as unreadable:
        raise Unusable(f"--json-file could not be read: {unreadable.strerror}") from unreadable


def player_from(arguments: argparse.Namespace, side: str, environment: dict) -> calls.Player:
    token = environment.get(TOKEN_VARIABLE, "")
    base_url = arguments.base_url or environment.get(PLATFORM_VARIABLE, "")
    round_id = arguments.round if arguments.round is not None else environment.get(ROUND_VARIABLE)
    missing = [name for name, value in ((TOKEN_VARIABLE, token), (f"--base-url or {PLATFORM_VARIABLE}", base_url),
                                         (f"--round or {ROUND_VARIABLE}", round_id)) if not value]
    if missing:
        raise Unusable(f"set {', '.join(missing)}")
    try:
        return calls.Player(base_url=base_url, token=token, round_id=int(round_id), side=side)
    except ValueError as wrong:
        raise Unusable(f"the round id must be a number, not {round_id!r}") from wrong


def side_of_operation(name: str, chosen: str | None) -> str:
    holding = [side for side in tools.SIDES if name in tools.offered(side)]
    if not holding:
        raise Unusable(f"no player has a tool named {name!r}; see python -m bots.cli tools --side <side>")
    if chosen:
        if chosen not in holding:
            raise Unusable(f"the {chosen} player has no tool named {name!r}")
        return chosen
    if name == tools.SHELL:
        raise Unusable(f"{name} runs on the attacker box or the WAF: name the box with --side")
    return holding[0]


def parsed_call(text: str) -> tuple[str, dict]:
    try:
        asked = json.loads(text)
    except ValueError as wrong:
        raise Unusable(f"stdin is not JSON: {wrong}") from wrong
    if not isinstance(asked, dict) or not isinstance(asked.get("name"), str):
        raise Unusable('stdin must be {"name": "<tool>", "arguments": {...}}')
    return asked["name"], asked.get("arguments", asked.get("input", {}))


def exit_code(outcome: dict) -> int:
    if not outcome.get("local"):
        return 0
    codes = {error.get("code") for error in outcome.get("errors", [])}
    return UNREACHABLE if "unreachable" in codes else USAGE_ERROR


def tests_dir(environment: dict) -> Path:
    given = environment.get(TESTS_DIR_VARIABLE)
    return Path(given) if given else Path.home() / ".cache" / "cr-bots" / "tests"


def round_dir(player: calls.Player, environment: dict) -> Path:
    return tests_dir(environment) / f"round-{player.round_id}"


def job_path(folder: Path, test: str, number: int) -> Path:
    return folder / f"{test}-{number}.json"


def job_numbers(folder: Path, test: str) -> list[int]:
    suffixes = (path.stem.removeprefix(f"{test}-") for path in folder.glob(f"{test}-*.json"))
    return sorted(int(suffix) for suffix in suffixes if suffix.isdigit())


def written(path: Path, job: dict) -> None:
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(job, ensure_ascii=False))
    os.replace(partial, path)


def alive(pid) -> bool:
    if not isinstance(pid, int):
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextmanager
def locked(folder: Path):
    with open(folder / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def running_job(folder: Path, test: str) -> int | None:
    for number in reversed(job_numbers(folder, test)):
        job = json.loads(job_path(folder, test, number).read_text())
        if "outcome" not in job and alive(job.get("pid")):
            return number
    return None


def spawned_worker(path: Path) -> int:
    worker = subprocess.Popen([sys.executable, "-m", "bots.cli", FINISH_TEST, str(path)], stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return worker.pid


def poll_command(test: str, number: int) -> str:
    return f"python -m bots.cli {TEST_RESULTS[test]} --job {number}"


def started_test(player: calls.Player, test: str, arguments, environment: dict,
                 spawn: Callable[[Path], int] = spawned_worker) -> dict:
    try:
        _, spec = calls.spec_of(player, test)
        arguments = calls.checked_arguments(spec, arguments)
    except calls.Refused as refused:
        return refused.outcome(test)
    folder = round_dir(player, environment)
    folder.mkdir(parents=True, exist_ok=True)
    with locked(folder):
        running = running_job(folder, test)
        if running is not None:
            return {"operation": test, "ok": False, "status": None, "local": True,
                    "errors": [{"path": "", "code": "test_running", "params": {"job": running},
                                "message": f"job {running} is still running: wait for it with "
                                           f"{poll_command(test, running)}"}]}
        number = max(job_numbers(folder, test), default=0) + 1
        path = job_path(folder, test, number)
        job = {"job": number, "operation": test, "side": player.side, "round": player.round_id,
               "base_url": player.base_url, "arguments": arguments, "started_at": time.time()}
        written(path, job)
        written(path, {**job, "pid": spawn(path)})
    return {"operation": test, "ok": True, "status": None, "running": True, "job": number,
            "poll": poll_command(test, number)}


def polled_test(player: calls.Player, result: str, number: int, environment: dict) -> dict:
    test = TEST_OF_RESULT[result]
    path = job_path(round_dir(player, environment), test, number)
    try:
        job = json.loads(path.read_text())
    except (OSError, ValueError):
        return calls.Refused("unknown_job", "job", f"no {test} job {number} in round {player.round_id}").outcome(result)
    if "outcome" in job:
        return job["outcome"]
    if not alive(job.get("pid")):
        return calls.Refused("job_lost", "job", f"job {number} stopped without an answer").outcome(result)
    return {"operation": result, "ok": True, "status": None, "running": True, "job": number,
            "running_s": round(time.time() - float(job["started_at"]))}


def finished_test(path: Path, environment: dict) -> int:
    job = json.loads(path.read_text())
    player = calls.Player(base_url=job["base_url"], token=environment.get(TOKEN_VARIABLE, ""),
                          round_id=int(job["round"]), side=job["side"])
    try:
        outcome = calls.call(player, job["operation"], job["arguments"])
    except Exception as failed:
        outcome = calls.Refused("job_failed", "", f"{type(failed).__name__}: {failed}").outcome(job["operation"])
    with locked(path.parent):
        written(path, {**json.loads(path.read_text()), "outcome": outcome})
    return 0


def outcome_of_call(player: calls.Player, name: str, arguments, environment: dict) -> dict:
    if name in TEST_RESULTS:
        return started_test(player, name, arguments, environment)
    return calls.call(player, name, arguments)


def made_call(player: calls.Player, name: str, arguments, out: TextIO, environment: dict) -> int:
    outcome = outcome_of_call(player, name, arguments, environment)
    print(calls.printed(outcome), file=out)
    return exit_code(outcome)


def operation_mode(argv: list[str], out: TextIO, environment: dict) -> int:
    name, rest = argv[0], argv[1:]
    arguments = operation_parser(name).parse_args(rest)
    if arguments.job is not None:
        if name not in TEST_OF_RESULT:
            raise Unusable(f"--job goes with {' or '.join(TEST_OF_RESULT)}, not {name}")
        player = player_from(arguments, side_of_operation(name, arguments.side), environment)
        outcome = polled_test(player, name, arguments.job, environment)
        print(calls.printed(outcome), file=out)
        return exit_code(outcome)
    try:
        given = json.loads(arguments_text(arguments))
    except ValueError as wrong:
        raise Unusable(f"the arguments are not JSON: {wrong}") from wrong
    player = player_from(arguments, side_of_operation(name, arguments.side), environment)
    return made_call(player, name, given, out, environment)


def run(arguments: argparse.Namespace, out: TextIO, environment: dict) -> int:
    player = player_from(arguments, arguments.side, environment)
    try:
        chosen = provider.load(arguments.provider)
    except provider.ProviderNotFound as missing:
        raise Unusable(str(missing)) from missing

    def report(entry: dict) -> None:
        print(json.dumps(entry, ensure_ascii=False), file=out, flush=True)

    played = play.play(player, chosen, turns=arguments.turns, report=report)
    report({"role": "end", "reason": played.reason, "turns": played.turns})
    return 0


def main(argv: list[str] | None = None, stdin: TextIO | None = None, out: TextIO | None = None,
         environment: dict | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    stdin, out = stdin or sys.stdin, out or sys.stdout
    environment = dict(os.environ if environment is None else environment)
    try:
        if argv and argv[0] not in COMMANDS and not argv[0].startswith("-"):
            return operation_mode(argv, out, environment)
        arguments = parser().parse_args(argv)
        if arguments.command == "tools":
            print(json.dumps(tools.specs(arguments.side), indent=2), file=out)
            return 0
        if arguments.command == "prompt":
            print(play.system_prompt(arguments.side, driving_the_cli=not arguments.loop), file=out)
            return 0
        if arguments.command == FINISH_TEST:
            return finished_test(Path(arguments.job_file), environment)
        if arguments.command == "call":
            player = player_from(arguments, arguments.side, environment)
            name, given = parsed_call(stdin.read())
            return made_call(player, name, given, out, environment)
        return run(arguments, out, environment)
    except Unusable as unusable:
        print(f"bots.cli: {unusable}", file=sys.stderr)
        return USAGE_ERROR


if __name__ == "__main__":
    sys.exit(main())
