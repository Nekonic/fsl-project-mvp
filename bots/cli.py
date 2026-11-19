from __future__ import annotations

import argparse
import json
import os
import sys
from typing import TextIO

from bots import calls, play, provider, tools

TOKEN_VARIABLE = "CR_SEAT_TOKEN"
PLATFORM_VARIABLE = "CR_PLATFORM_URL"
ROUND_VARIABLE = "CR_ROUND"
COMMANDS = ("tools", "prompt", "call", "run")
USAGE_ERROR = 2
UNREACHABLE = 3


class Unusable(RuntimeError):
    pass


def side_argument(parser: argparse.ArgumentParser, required: bool = True) -> None:
    parser.add_argument("--side", choices=tools.SIDES, required=required)


def seat_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--round", type=int, default=None, help=f"the round id (default: ${ROUND_VARIABLE})")
    parser.add_argument("--base-url", default=None, help=f"the platform's base URL (default: ${PLATFORM_VARIABLE})")


def parser() -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(
        prog="python -m bots.cli",
        description=f"Drive one seat of a round through the attack or defence API. The seat token is read from "
                    f"${TOKEN_VARIABLE}. Also: python -m bots.cli <tool> --json '{{...}}'.")
    commands = made.add_subparsers(dest="command", required=True)
    side_argument(commands.add_parser("tools", help="print the tool specs of a side as JSON"))
    prompt = commands.add_parser("prompt", help="print the system prompt of a side")
    side_argument(prompt)
    prompt.add_argument("--loop", action="store_true", help="the prompt a provider loop gets, without the CLI part")
    call = commands.add_parser("call", help="read {name, arguments} as JSON on stdin and make that one call")
    side_argument(call)
    seat_arguments(call)
    run = commands.add_parser("run", help="let a provider play the seat until it stops or runs out of turns")
    side_argument(run)
    seat_arguments(run)
    run.add_argument("--provider", required=True, help="package.module:factory returning a provider")
    run.add_argument("--turns", type=int, default=play.DEFAULT_TURNS)
    return made


def operation_parser(name: str) -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(prog=f"python -m bots.cli {name}")
    side_argument(made, required=False)
    seat_arguments(made)
    made.add_argument("--json", default="{}", help="the tool's arguments as a JSON object")
    return made


def seat_from(arguments: argparse.Namespace, side: str, environment: dict) -> calls.Seat:
    token = environment.get(TOKEN_VARIABLE, "")
    base_url = arguments.base_url or environment.get(PLATFORM_VARIABLE, "")
    round_id = arguments.round if arguments.round is not None else environment.get(ROUND_VARIABLE)
    missing = [name for name, value in ((TOKEN_VARIABLE, token), (f"--base-url or {PLATFORM_VARIABLE}", base_url),
                                         (f"--round or {ROUND_VARIABLE}", round_id)) if not value]
    if missing:
        raise Unusable(f"set {', '.join(missing)}")
    try:
        return calls.Seat(base_url=base_url, token=token, round_id=int(round_id), side=side)
    except ValueError as wrong:
        raise Unusable(f"the round id must be a number, not {round_id!r}") from wrong


def side_of_operation(name: str, chosen: str | None) -> str:
    holding = [side for side in tools.SIDES if name in tools.operations(side)]
    if not holding:
        raise Unusable(f"no seat has a tool named {name!r}; see python -m bots.cli tools --side <side>")
    if chosen:
        if chosen not in holding:
            raise Unusable(f"the {chosen} seat has no tool named {name!r}")
        return chosen
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


def made_call(seat: calls.Seat, name: str, arguments, out: TextIO) -> int:
    outcome = calls.call(seat, name, arguments)
    print(calls.printed(outcome), file=out)
    return exit_code(outcome)


def operation_mode(argv: list[str], out: TextIO, environment: dict) -> int:
    name, rest = argv[0], argv[1:]
    arguments = operation_parser(name).parse_args(rest)
    try:
        given = json.loads(arguments.json)
    except ValueError as wrong:
        raise Unusable(f"--json is not JSON: {wrong}") from wrong
    seat = seat_from(arguments, side_of_operation(name, arguments.side), environment)
    return made_call(seat, name, given, out)


def run(arguments: argparse.Namespace, out: TextIO, environment: dict) -> int:
    seat = seat_from(arguments, arguments.side, environment)
    try:
        chosen = provider.load(arguments.provider)
    except provider.ProviderNotFound as missing:
        raise Unusable(str(missing)) from missing

    def report(entry: dict) -> None:
        print(json.dumps(entry, ensure_ascii=False), file=out, flush=True)

    played = play.play(seat, chosen, turns=arguments.turns, report=report)
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
        if arguments.command == "call":
            seat = seat_from(arguments, arguments.side, environment)
            name, given = parsed_call(stdin.read())
            return made_call(seat, name, given, out)
        return run(arguments, out, environment)
    except Unusable as unusable:
        print(f"bots.cli: {unusable}", file=sys.stderr)
        return USAGE_ERROR


if __name__ == "__main__":
    sys.exit(main())
