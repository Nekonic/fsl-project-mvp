from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

from bots import play, rest, signin, tools
from bots.relay import Relay
from bots.watch import Unread, Watch, interval_of, next_start

PLATFORM_VARIABLE = "CR_PLATFORM_URL"
KEY_FILE_VARIABLE = "CR_BOT_LAUNCHER_KEY_FILE"
CREDENTIAL_FILE_VARIABLE = "CR_CLAUDE_TOKEN_FILE"
RUNS_MAX_VARIABLE = "CR_BOT_RUNS_MAX"
POLL_VARIABLE = "CR_BOT_POLL_SECONDS"
RUN_SECONDS_VARIABLE = "CR_BOT_RUN_SECONDS"
USERS_VARIABLE = "CR_BOT_USERS"
DEFAULT_KEY_FILE = "/run/secrets/bots_launcher_key"
DEFAULT_CREDENTIAL_FILE = "/run/secrets/claude_oauth_token"
DEFAULT_USERS = tuple(f"bot{number}" for number in range(8))
CREDENTIAL_VARIABLE = "CLAUDE_CODE_OAUTH_TOKEN"

CLAUDE = "claude"
CLAUDE_CODE_VERSION_VARIABLE = "CR_CLAUDE_CODE_VERSION"
STOP_GRACE_SECONDS = 15.0
ALLOWED = ("Bash(python -m bots.cli *)", "Bash(sleep *)", "Edit(/*.json)")
DENIED = ("mcp__*", "Bash(cat *)", "Bash(head *)", "Bash(tail *)", "Bash(less *)", "Bash(more *)", "Bash(grep *)",
          "Bash(rg *)", "Bash(find *)", "Bash(ls *)", "Bash(tree *)", "Bash(stat *)", "Bash(file *)", "Bash(wc *)",
          "Bash(diff *)", "Bash(strings *)", "Bash(od *)", "Bash(xxd *)", "Bash(env *)", "Bash(printenv *)",
          "Bash(set *)", "Bash(export *)", "Bash(declare *)", "Bash(echo *)", "Bash(printf *)", "Bash(id *)",
          "Bash(ps *)", "Bash(cd *)", "Bash(paste *)", "Bash(fold *)", "Bash(fmt *)", "Bash(pr *)",
          "Bash(expand *)", "Bash(unexpand *)", "Bash(comm *)", "Bash(tsort *)", "Bash(numfmt *)", "Bash(cut *)",
          "Bash(nl *)", "Bash(tac *)", "Bash(rev *)", "Bash(hexdump *)", "Bash(cmp *)", "Bash(column *)",
          "Bash(tr *)", "Bash(sort *)", "Bash(uniq *)", "Bash(base64 *)", "Bash(sed *)", "Bash(awk *)")
RUN_SCRIPT = ('umask 077 && rm -rf "$HOME/run" && mkdir -p "$HOME/run/work" "$HOME/run/config" '
              '&& head -c "$1" > "$HOME/run/config/system.md" && shift && cd "$HOME/run/work" '
              '&& export CLAUDE_CONFIG_DIR="$HOME/run/config" && exec "$@"')
SYSTEM_FILE = "../config/system.md"
INLINE_OUTPUT_MAX = 128000
CHILD_SETTINGS = json.dumps({"bashOutputMaxChars": INLINE_OUTPUT_MAX})
CHILD_PASSED = ("CR_PLATFORM_URL", "CR_PLAYER_TOKEN", "CR_ROUND", tools.STEP_OPERATIONS_VARIABLE, CREDENTIAL_VARIABLE,
                "PYTHONPATH", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_AUTOUPDATER")

HIDDEN = "[hidden]"
SECRET_SHAPE = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")
NOTE_TEXT_MAX = 2000
CLOSING_MAX = 10000
FLUSH_SECONDS = 5.0
WATCH_READ_TIMEOUT_S = 5.0
CHECK_SHARE = 0.8
REFUSAL_SUBTYPES = frozenset({"model_refusal_fallback", "model_refusal_no_fallback"})
SAFEGUARD_NOTICE = "safeguards stopped"
TIMED_OUT = "timed_out"
CRASHED = "crashed"
FAILED_RUN = "error"
OUT_OF_TURNS = "error_max_turns"
OUT_OF_BUDGET = "error_max_budget_usd"
WATCHED_SIDES = frozenset({"defence"})


def log(text: str) -> None:
    print(f"bots.launcher: {text}", file=sys.stderr, flush=True)


def read_secret(path: str) -> str:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


@dataclass(frozen=True)
class Settings:
    platform_url: str
    launcher_key: str
    credential: str
    runs_max: int
    poll_s: float
    run_seconds: float
    users: tuple[str | None, ...]

    @classmethod
    def of(cls, environment: Mapping[str, str]) -> Settings:
        asked = int(environment.get(RUNS_MAX_VARIABLE) or 2)
        named = tuple(name for name in environment.get(USERS_VARIABLE, ",".join(DEFAULT_USERS)).split(",") if name)
        users = named[:asked] if named else (None,) * asked
        return cls(platform_url=environment.get(PLATFORM_VARIABLE, "http://platform:8000").rstrip("/"),
                   launcher_key=read_secret(environment.get(KEY_FILE_VARIABLE, DEFAULT_KEY_FILE)),
                   credential=read_secret(environment.get(CREDENTIAL_FILE_VARIABLE, DEFAULT_CREDENTIAL_FILE)),
                   runs_max=len(users), poll_s=float(environment.get(POLL_VARIABLE) or 5),
                   run_seconds=float(environment.get(RUN_SECONDS_VARIABLE) or 7200), users=users)


def masked(text: str, hidden: tuple[str, ...]) -> str:
    for secret in hidden:
        if secret:
            text = text.replace(secret, HIDDEN)
    return SECRET_SHAPE.sub(HIDDEN, text)


def now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Transcript:
    hidden: tuple[str, ...]
    notes: list[dict] = field(default_factory=list)
    refusals: int = 0
    turns: int = 0
    result: dict | None = None
    ended_by: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def note(self, kind: str, text: str) -> None:
        with self.lock:
            self.notes.append({"at": now_text(), "kind": kind, "text": masked(str(text), self.hidden)[:NOTE_TEXT_MAX]})

    def taken(self) -> list[dict]:
        with self.lock:
            taken, self.notes = self.notes, []
        return taken

    def take(self, event: Mapping) -> None:
        kind, subtype = event.get("type"), event.get("subtype")
        if kind == "assistant":
            message = event.get("message") or {}
            for block in message.get("content") or []:
                if block.get("type") == "text" and block.get("text", "").strip():
                    self.note("text", block["text"])
                elif block.get("type") == "tool_use":
                    given = block.get("input") or {}
                    self.note("call", given.get("command") or f"{block.get('name')} {json.dumps(given)}")
            if message.get("stop_reason") == "refusal":
                self.refusals += 1
        elif kind == "system" and subtype == "init":
            log(f"model {event.get('model')}")
        elif kind == "system" and subtype == "permission_denied":
            self.note("denied", event.get("message") or json.dumps(event.get("tool_input") or {}))
        elif kind == "system" and subtype in REFUSAL_SUBTYPES:
            self.refusals += 1
            self.note("refused", f"{subtype} {event.get('original_model')} -> {event.get('fallback_model')} "
                                 f"[{event.get('api_refusal_category')}]: {event.get('content')}")
        elif kind == "system" and subtype == "informational" and SAFEGUARD_NOTICE in str(event.get("content")):
            self.refusals += 1
            self.note("refused", event.get("content"))
        elif kind == "result":
            self.result = dict(event)
            self.turns += int(event.get("num_turns") or 0)
            log(masked(f"{subtype} error={bool(event.get('is_error'))} turns={event.get('num_turns')} "
                       f"cost_usd={event.get('total_cost_usd')}", self.hidden))
            if event.get("is_error") and isinstance(event.get("result"), str):
                log(masked(event["result"], self.hidden)[:NOTE_TEXT_MAX])

    def spent(self, max_turns: int, budget_usd: float) -> str | None:
        result = self.result or {}
        if result.get("subtype") in (OUT_OF_TURNS, OUT_OF_BUDGET):
            return str(result["subtype"])
        if self.turns >= max_turns:
            return OUT_OF_TURNS
        if float(result.get("total_cost_usd") or 0) >= budget_usd:
            return OUT_OF_BUDGET
        return None

    def finish(self, returncode: int | None, timed_out: bool) -> dict:
        result = self.result or {}
        if timed_out:
            exit_reason = TIMED_OUT
        elif self.ended_by:
            exit_reason = self.ended_by
        elif result.get("is_error") and result.get("subtype") not in (OUT_OF_TURNS, OUT_OF_BUDGET):
            exit_reason = FAILED_RUN
        else:
            exit_reason = str(result.get("subtype") or CRASHED) if result or returncode == 0 else CRASHED
        closing = result.get("result") if isinstance(result.get("result"), str) and not result.get("is_error") else ""
        return {"exit": exit_reason[:32], "cost_usd": result.get("total_cost_usd"), "turns": self.turns or None,
                "refusals": self.refusals, "closing": masked(closing, self.hidden)[:CLOSING_MAX]}


def pace_note(pace: Mapping) -> str:
    return (f"Your difficulty step allows {pace['per_window']} actions in any {pace['window_s']} seconds, at least "
            f"{pace['min_gap_s']} seconds apart.")


def watch_note(claimed: Mapping) -> str:
    return f"The launcher checks the round for news every {interval_of(claimed):g} seconds."


def system_text(claimed: Mapping) -> str:
    side = claimed["side"]
    parts = [play.system_prompt(side, driving_the_cli=True), pace_note(claimed["pace"])]
    if side in WATCHED_SIDES:
        parts.append(watch_note(claimed))
    stance = (claimed.get("prompt") or {}).get("stance") if side == "attack" else None
    if stance:
        parts.append(stance)
    return "\n\n".join(parts)


RANGE_CONTEXT = ("The target is a practice web application this platform deploys for the round in an isolated "
                 "OpenStack range owned and operated by the platform's operator, only that target is in scope, the "
                 "round trains the defender who watches with Suricata and ModSecurity, and the operator who started "
                 "the round authorised the attack.")
ENGAGEMENT = ("This is an authorised red-team exercise in the operator's isolated OpenStack training range: the range "
              "operator who started this round authorised it, its scope is this round's target hosts listed in the "
              "state below and nothing else, its purpose is to train and score the defender, and you act only "
              "through the bots.cli attack API and its shell until the round ends, then leave an intent note for "
              "the debrief.")


def opening_text(claimed: Mapping, state) -> str:
    side = claimed["side"]
    if side == "attack":
        return (f"Round {claimed['round']}: you hold the attack player. {ENGAGEMENT} The engagement state, read "
                f"just now with attack_state:\n{json.dumps(state, ensure_ascii=False)}")
    return (f"Round {claimed['round']}: you hold the {side} player. {RANGE_CONTEXT} Your player's state, read just "
            f"now with {side}_state:\n{json.dumps(state, ensure_ascii=False)}")


def claude_command(claimed: Mapping) -> list[str]:
    return [CLAUDE, "-p", "--input-format", "stream-json", "--append-system-prompt-file", SYSTEM_FILE,
            "--model", str(claimed["model"]),
            "--max-budget-usd", str(claimed["budget_usd"]), "--max-turns", str(claimed["max_turns"]),
            "--output-format", "stream-json", "--verbose", "--tools", "Bash,Write", "--allowedTools", *ALLOWED,
            "--disallowedTools", *DENIED, "--permission-mode", "dontAsk", "--strict-mcp-config", "--safe-mode",
            "--setting-sources", "", "--settings", CHILD_SETTINGS, "--disable-slash-commands",
            "--no-session-persistence"]


def child_command(claimed: Mapping, system_bytes: int, user: str | None) -> list[str]:
    script = ["sh", "-c", RUN_SCRIPT, "bot-run", str(system_bytes), *claude_command(claimed)]
    if user is None:
        return script
    return ["sudo", "-u", user, "-H", f"--preserve-env={','.join(CHILD_PASSED)}", "--", *script]


def child_environment(settings: Settings, relay_url: str, run_key: str, claimed: Mapping,
                      home: str | None) -> dict[str, str]:
    environment = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                   "CR_PLATFORM_URL": relay_url, "CR_PLAYER_TOKEN": run_key, "CR_ROUND": str(claimed["round"]),
                   tools.STEP_OPERATIONS_VARIABLE: ",".join(claimed["allowance"]["operations"]),
                   CREDENTIAL_VARIABLE: settings.credential, "PYTHONPATH": str(tools.ROOT),
                   "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1"}
    if home is not None:
        environment["HOME"] = home
    return environment


def launcher_session(settings: Settings) -> signin.Platform:
    return signin.Platform(settings.platform_url, timeout=60.0, token=settings.launcher_key)


def state_of(settings: Settings, claimed: Mapping):
    try:
        answer = rest.request(signin.playing(settings.platform_url, claimed["token"], 60.0),
                              f"{claimed['side']}_state", round_id=claimed["round"])
        return answer.json()
    except (requests.RequestException, ValueError) as unreadable:
        return {"unread": str(unreadable)}


class CheckReader:
    def __init__(self, settings: Settings, claimed: Mapping, read_timeout_s: float = WATCH_READ_TIMEOUT_S):
        self.session = signin.playing(settings.platform_url, claimed["token"], read_timeout_s)
        self.claimed = claimed
        self.hidden = (claimed["token"], settings.launcher_key, settings.credential)
        self.read_timeout_s = read_timeout_s
        self.deadline = 0.0
        self.statuses: list[str] = []

    def begin(self, budget_s: float) -> None:
        self.deadline = time.monotonic() + budget_s
        self.statuses = []

    def failed(self, operation: str, why: str):
        self.statuses.append(f"{operation} failed ({why})")
        raise Unread(operation)

    def __call__(self, operation: str, params: dict) -> Mapping:
        left = self.deadline - time.monotonic()
        if left <= 0:
            return self.failed(operation, "not sent, the check's time is spent")
        self.session.timeout = min(self.read_timeout_s, left)
        try:
            answer = rest.request(self.session, operation, round_id=self.claimed["round"], **params)
        except requests.RequestException as unreachable:
            return self.failed(operation, f"{type(unreachable).__name__}: {unreachable}")
        if answer.status_code != 200:
            return self.failed(operation, f"answered {answer.status_code}: {answer.text[:200]}")
        try:
            found = answer.json()
        except ValueError:
            return self.failed(operation, f"answered 200 with no JSON: {answer.text[:200]}")
        if not isinstance(found, dict):
            return self.failed(operation, "answered 200 with no JSON object")
        self.statuses.append(f"{operation} 200")
        return found

    def summary(self, took_s: float, budget_s: float) -> str:
        line = (f"run {self.claimed['run']}: watch check {took_s:.1f} s of {budget_s:.1f} s: "
                f"{', '.join(self.statuses) or 'no reads'}")
        return " ".join(masked(line, self.hidden).split())[:NOTE_TEXT_MAX]


def check_budget(interval: float) -> float:
    return interval * CHECK_SHARE


def checked(watch: Watch, reader: CheckReader, budget_s: float) -> None:
    reader.begin(budget_s)
    started = time.monotonic()
    watch.tick()
    log(reader.summary(time.monotonic() - started, budget_s))


def user_message(text: str) -> str:
    return json.dumps({"type": "user", "message": {"role": "user", "content": text},
                       "parent_tool_use_id": None}, ensure_ascii=False) + "\n"


class Conversation:
    def __init__(self, stdin):
        self.stdin = stdin
        self.lock = threading.Lock()
        self.closed = False

    def say(self, text: str) -> None:
        with self.lock:
            if self.closed:
                return
            try:
                self.stdin.write(user_message(text))
                self.stdin.flush()
            except (OSError, ValueError):
                self.closed = True

    def close(self) -> None:
        with self.lock:
            if self.closed:
                return
            self.closed = True
            try:
                self.stdin.close()
            except (OSError, ValueError):
                pass


def followed(event: Mapping, transcript: Transcript, claimed: Mapping, watch: Watch) -> None:
    if event.get("type") != "result":
        return
    spent = transcript.spent(int(claimed["max_turns"]), float(claimed["budget_usd"]))
    if spent and not watch.closed:
        transcript.ended_by = spent
        watch.stop()
    else:
        watch.turn_ended()


def reported(session: signin.Platform, run: int, notes: list[dict]) -> None:
    if not notes:
        return
    try:
        rest.request(session, "bot_run_report", body={"notes": notes}, run_id=run)
    except requests.RequestException as unreachable:
        log(f"run {run}: {len(notes)} notes not reported: {unreachable}")


def played(settings: Settings, claimed: Mapping, user: str | None) -> None:
    run = claimed["run"]
    run_key = secrets.token_urlsafe(32)
    transcript = Transcript(hidden=(claimed["token"], run_key, settings.credential, settings.launcher_key))
    relay = Relay(settings.platform_url, claimed["token"], run_key, claimed,
                  report=lambda text: transcript.note("refused", text))
    session = launcher_session(settings)
    stop = threading.Event()
    timed_out = threading.Event()
    returncode = None
    scratch = tempfile.TemporaryDirectory(prefix="cr-bot-home-") if user is None else None
    try:
        relay_url = relay.start()
        state = state_of(settings, claimed)
        system = system_text(claimed)
        child = subprocess.Popen(child_command(claimed, len(system.encode()), user), stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                 env=child_environment(settings, relay_url, run_key, claimed,
                                                       scratch.name if scratch else None),
                                 cwd="/")
        child.stdin.write(system)
        conversation = Conversation(child.stdin)
        conversation.say(opening_text(claimed, state))
        watch = None
        reader = None
        if claimed["side"] in WATCHED_SIDES:
            reader = CheckReader(settings, claimed)
            watch = Watch(reader, conversation.say, conversation.close, state.get("phase"))
        else:
            conversation.close()

        def flushing():
            while not stop.wait(FLUSH_SECONDS):
                reported(session, run, transcript.taken())

        def overdue():
            if not stop.wait(settings.run_seconds):
                timed_out.set()
                stopped(child, user)

        def watching():
            interval = interval_of(claimed)
            started = time.monotonic()
            while not watch.closed:
                started = next_start(started, interval, time.monotonic())
                if stop.wait(max(0.0, started - time.monotonic())) or watch.closed:
                    return
                checked(watch, reader, check_budget(interval))

        threading.Thread(target=flushing, daemon=True).start()
        threading.Thread(target=overdue, daemon=True).start()
        if watch is not None:
            threading.Thread(target=watching, daemon=True).start()
        for line in child.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                transcript.take(event)
                if watch is not None:
                    followed(event, transcript, claimed, watch)
        conversation.close()
        returncode = child.wait()
    except OSError as unstartable:
        log(f"run {run}: the bot did not start: {unstartable}")
    finally:
        stop.set()
        relay.stop()
        if scratch is not None:
            scratch.cleanup()
    reported(session, run, transcript.taken())
    finished = transcript.finish(returncode, timed_out.is_set())
    try:
        rest.request(session, "bot_run_finish", body=finished, run_id=run)
    except requests.RequestException as unreachable:
        log(f"run {run}: finish not reported: {unreachable}")
    log(f"run {run}: {finished['exit']} turns={finished['turns']} cost_usd={finished['cost_usd']}")


def stopped(child: subprocess.Popen, user: str | None) -> None:
    child.terminate()
    try:
        child.wait(timeout=STOP_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    if user is not None:
        subprocess.run(["sudo", "-u", user, "--", sys.executable, "-c",
                        "import os, signal; os.kill(-1, signal.SIGKILL)"],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    child.kill()


def launcher_profile(environment: Mapping[str, str]) -> dict:
    prompts = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(play.PROMPTS.glob("*.md"))}
    return {"prompts": prompts, "claude_code": environment.get(CLAUDE_CODE_VERSION_VARIABLE, "")}


def claim(session: signin.Platform, restarted: bool) -> dict | None:
    answer = rest.request(session, "bot_run_claim",
                          body={"restarted": restarted, "launcher": launcher_profile(os.environ)})
    if answer.status_code == 204:
        return None
    if answer.status_code != 200:
        raise requests.RequestException(f"claim answered {answer.status_code}: {answer.content[:200]!r}")
    return answer.json()


def serve(settings: Settings) -> None:
    session = launcher_session(settings)
    busy: dict[int, threading.Thread] = {}
    restarted = True
    warned = False
    while True:
        busy = {seat: thread for seat, thread in busy.items() if thread.is_alive()}
        free = [seat for seat in range(settings.runs_max) if seat not in busy]
        if not settings.credential or not settings.launcher_key:
            if not warned:
                log("no launcher key or Claude credential in the secrets: claiming nothing")
                warned = True
        elif free:
            try:
                claimed = claim(session, restarted)
                restarted = False
            except requests.RequestException as unreachable:
                log(f"claim failed: {unreachable}")
                claimed = None
            if claimed is not None:
                seat = free[0]
                log(f"run {claimed['run']}: round {claimed['round']} {claimed['side']} step {claimed['step']}")
                busy[seat] = threading.Thread(target=played, args=(settings, claimed, settings.users[seat]),
                                              daemon=True)
                busy[seat].start()
                continue
        time.sleep(settings.poll_s)


def main() -> int:
    serve(Settings.of(os.environ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
