"""Suricata rule validation and reload. The only file that knows the process.

The platform container has no suricata binary, so it runs `suricata -T` inside
the IDS container over the Docker socket. That socket is a container escape
path: production should put a sidecar in front of Suricata instead. Isolated
here so the swap touches one file.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

RELOAD_SIGNAL = "USR2"
_TIMEOUT = 60


class RuleApplyError(RuntimeError):
    """The rules were not applied. The previous rule set is still live."""


@dataclass(frozen=True)
class ValidationOutcome:
    ok: bool
    output: str


def current() -> str:
    """Contents of the rule file that is currently in effect."""
    return _read_rules()


def validate(content: str) -> ValidationOutcome:
    """Write the candidate file and check it with `suricata -T`. Applies nothing."""
    _write_candidate(content)
    result = _run(
        [
            "docker",
            "exec",
            settings.SURICATA_CONTAINER,
            "suricata",
            "-T",
            "-S",
            settings.SURICATA_CANDIDATE_PATH_IN_IDS,
        ]
    )
    output = (result.stdout or "") + (result.stderr or "")
    return ValidationOutcome(ok=result.returncode == 0, output=output.strip())


def apply(content: str) -> None:
    """Write rules that passed validation, then reload Suricata."""
    outcome = validate(content)
    if not outcome.ok:
        raise RuleApplyError(outcome.output)

    previous = _read_rules()
    _write_rules(content)

    result = _run(["docker", "kill", "-s", RELOAD_SIGNAL, settings.SURICATA_CONTAINER])
    if result.returncode != 0:
        _write_rules(previous)
        raise RuleApplyError(
            "reload failed, rolled back to the previous rule set: "
            + ((result.stdout or "") + (result.stderr or "")).strip()
        )


def _run(command: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(
            args=command, returncode=1, stdout="", stderr=str(exc)
        )


def _read_rules() -> str:
    path = Path(settings.SURICATA_RULE_PATH)
    return path.read_text() if path.exists() else ""


def _write_rules(content: str) -> None:
    Path(settings.SURICATA_RULE_PATH).write_text(content)


def _write_candidate(content: str) -> None:
    Path(settings.SURICATA_CANDIDATE_PATH).write_text(content)
