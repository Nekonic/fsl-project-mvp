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
ALLOWED = ("Bash(python -m bots.cli *)", "Bash(sleep *)")
DENIED = ("mcp__*", "Bash(cat *)", "Bash(head *)", "Bash(tail *)", "Bash(less *)", "Bash(more *)", "Bash(grep *)",
          "Bash(rg *)", "Bash(find *)", "Bash(ls *)", "Bash(tree *)", "Bash(stat *)", "Bash(file *)", "Bash(wc *)",
          "Bash(diff *)", "Bash(strings *)", "Bash(od *)", "Bash(xxd *)", "Bash(env *)", "Bash(printenv *)",
          "Bash(set *)", "Bash(export *)", "Bash(declare *)", "Bash(echo *)", "Bash(printf *)", "Bash(id *)",
          "Bash(ps *)", "Bash(cd *)", "Bash(paste *)", "Bash(fold *)", "Bash(fmt *)", "Bash(pr *)",
          "Bash(expand *)", "Bash(unexpand *)", "Bash(comm *)", "Bash(tsort *)", "Bash(numfmt *)", "Bash(cut *)",
          "Bash(nl *)", "Bash(tac *)", "Bash(rev *)", "Bash(hexdump *)", "Bash(cmp *)", "Bash(column *)",
          "Bash(tr *)", "Bash(sort *)", "Bash(uniq *)", "Bash(base64 *)", "Bash(sed *)", "Bash(awk *)")
RUN_SCRIPT = ('umask 077 && rm -rf "$HOME/run" && mkdir -p "$HOME/run/work" "$HOME/run/config" '
              '&& cat > "$HOME/run/config/system.md" && cd "$HOME/run/work" '
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
REFUSAL_SUBTYPES = frozenset({"model_refusal_fallback", "model_refusal_no_fallback"})
TIMED_OUT = "timed_out"
CRASHED = "crashed"


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
    result: dict | None = None
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
        elif kind == "system" and subtype == "permission_denied":
            self.note("denied", event.get("message") or json.dumps(event.get("tool_input") or {}))
        elif kind == "system" and subtype in REFUSAL_SUBTYPES:
            self.refusals += 1
        elif kind == "result":
            self.result = dict(event)
            self.note("result", f"{subtype} turns={event.get('num_turns')} cost_usd={event.get('total_cost_usd')}")

    def finish(self, returncode: int | None, timed_out: bool) -> dict:
        result = self.result or {}
        if timed_out:
            exit_reason = TIMED_OUT
        else:
            exit_reason = str(result.get("subtype") or CRASHED) if result or returncode == 0 else CRASHED
        closing = result.get("result") if isinstance(result.get("result"), str) else ""
        return {"exit": exit_reason[:32], "cost_usd": result.get("total_cost_usd"), "turns": result.get("num_turns"),
                "refusals": self.refusals, "closing": masked(closing, self.hidden)[:CLOSING_MAX]}


def pace_note(pace: Mapping) -> str:
    return (f"Your difficulty step allows {pace['per_window']} actions in any {pace['window_s']} seconds, at least "
            f"{pace['min_gap_s']} seconds apart.")


def system_text(claimed: Mapping) -> str:
    side = claimed["side"]
    parts = [play.system_prompt(side, driving_the_cli=True), pace_note(claimed["pace"])]
    stance = (claimed.get("prompt") or {}).get("stance") if side == "attack" else None
    if stance:
        parts.append(stance)
    return "\n\n".join(parts)


def opening_text(claimed: Mapping, state) -> str:
    side = claimed["side"]
    return (f"Round {claimed['round']}: you hold the {side} player. Your player's state, read just now with "
            f"{side}_state:\n{json.dumps(state, ensure_ascii=False)}")


def claude_command(claimed: Mapping, opening: str) -> list[str]:
    return [CLAUDE, "-p", opening, "--append-system-prompt-file", SYSTEM_FILE, "--model", str(claimed["model"]),
            "--max-budget-usd", str(claimed["budget_usd"]), "--max-turns", str(claimed["max_turns"]),
            "--output-format", "stream-json", "--verbose", "--tools", "Bash", "--allowedTools", *ALLOWED,
            "--disallowedTools", *DENIED, "--permission-mode", "dontAsk", "--strict-mcp-config", "--safe-mode",
            "--setting-sources", "", "--settings", CHILD_SETTINGS, "--disable-slash-commands",
            "--no-session-persistence"]


def child_command(claimed: Mapping, opening: str, user: str | None) -> list[str]:
    script = ["sh", "-c", RUN_SCRIPT, "bot-run", *claude_command(claimed, opening)]
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
        opening = opening_text(claimed, state_of(settings, claimed))
        child = subprocess.Popen(child_command(claimed, opening, user), stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                 env=child_environment(settings, relay_url, run_key, claimed,
                                                       scratch.name if scratch else None),
                                 cwd="/")
        child.stdin.write(system_text(claimed))
        child.stdin.close()

        def flushing():
            while not stop.wait(FLUSH_SECONDS):
                reported(session, run, transcript.taken())

        def overdue():
            if not stop.wait(settings.run_seconds):
                timed_out.set()
                stopped(child, user)

        threading.Thread(target=flushing, daemon=True).start()
        threading.Thread(target=overdue, daemon=True).start()
        for line in child.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                transcript.take(event)
        returncode = child.wait()
    except OSError as unstartable:
        transcript.note("result", f"the bot did not start: {unstartable}")
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
