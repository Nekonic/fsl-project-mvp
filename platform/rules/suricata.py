"""Suricata 룰 검증과 반영. 스택에서 Suricata 프로세스를 아는 유일한 파일.

platform 컨테이너에는 suricata 바이너리가 없다. Docker 소켓을 통해 IDS
컨테이너 안에서 `suricata -T` 를 돌린다. 소켓 마운트는 컨테이너 탈출
경로이므로, 메인 레포에서는 IDS 쪽에 검증·반영만 노출하는 사이드카로
바꿔야 한다. 그 교체가 이 파일 하나로 끝나도록 격리해 두었다.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

RELOAD_SIGNAL = "USR2"
_TIMEOUT = 60


class RuleApplyError(RuntimeError):
    """룰을 반영하지 못했다. 이전 룰셋은 그대로 살아 있다."""


@dataclass(frozen=True)
class ValidationOutcome:
    ok: bool
    output: str


def current() -> str:
    """지금 반영되어 있는 룰 파일 내용."""
    return _read_rules()


def validate(content: str) -> ValidationOutcome:
    """후보 파일에 쓰고 `suricata -T` 로 검사한다. 반영하지 않는다."""
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
    """검증을 통과한 룰만 파일에 쓰고 Suricata 를 리로드한다."""
    outcome = validate(content)
    if not outcome.ok:
        raise RuleApplyError(outcome.output)

    previous = _read_rules()
    _write_rules(content)

    result = _run(["docker", "kill", "-s", RELOAD_SIGNAL, settings.SURICATA_CONTAINER])
    if result.returncode != 0:
        _write_rules(previous)
        raise RuleApplyError(
            "리로드에 실패해 직전 룰셋으로 되돌렸다: "
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
