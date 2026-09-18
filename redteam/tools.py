"""외부 공격 도구를 일회성 컨테이너로 돌린다.

케이스가 `tool:` 을 선언하면 하니스는 HTTP 요청을 직접 보내는 대신
이 모듈에 넘긴다. 도구는 스택 네트워크에 붙으므로 대상을 `localhost`
가 아니라 컨테이너 이름으로 부른다 — 케이스는 `{target}` 자리표시자를
쓰고 하니스가 내부 주소로 치환한다.

MVP 에서 지원하는 도구는 sqlmap 하나다. 마커 헤더를 주입할 수 있어야
ground truth 대응이 성립하는데, `--headers` 가 있는 도구가 그것뿐이다.
nmap 같은 비 HTTP 도구는 시간창 대응(correlation: window)으로 붙여야
하고, 그때는 도구 컨테이너의 IP 를 알아야 한다.
"""

from __future__ import annotations

import os
from typing import Any

MARKER_HEADER = "X-FSL-Case"

TOOL_IMAGE = os.environ.get("FSL_TOOL_IMAGE", "fsl-redteam-tools")
TOOL_NETWORK = os.environ.get("FSL_TOOL_NETWORK", "fsl_fsl")

# 도구 이름 -> 컨테이너 안에서 실행할 실행 파일.
SUPPORTED_TOOLS = {"sqlmap": "sqlmap"}


class UnsupportedTool(ValueError):
    """케이스가 이 MVP 가 모르는 도구를 선언했다."""


class ToolUnavailable(RuntimeError):
    """도구가 아예 실행되지 못했다. 공격이 나가지 않았으므로 ground truth 가
    거짓이 된다. 미탐으로 집계하면 방어가 아니라 하니스의 실패를 방어 실패로
    기록하는 셈이다."""


# docker 가 컨테이너를 시작조차 못했을 때 내는 코드. 도구 자신의 비정상
# 종료(sqlmap 이 주입점을 못 찾는 등)와 구분해야 한다.
DOCKER_STARTUP_FAILURE = 125


def is_tool_case(case: dict[str, Any]) -> bool:
    return bool(case.get("tool"))


def build_tool_command(case: dict[str, Any], target_url: str) -> list[str]:
    """케이스를 `docker run` argv 로 바꾼다.

    실행하지 않고 만들기만 한다 — 무엇이 실행될지 테스트로 고정할 수 있어야
    한다.
    """
    tool = case["tool"]
    executable = SUPPORTED_TOOLS.get(tool)
    if executable is None:
        raise UnsupportedTool(
            f"{tool!r} 은 지원하지 않는다. 지원하는 도구: "
            f"{', '.join(sorted(SUPPORTED_TOOLS))}"
        )

    args = [str(a).replace("{target}", target_url.rstrip("/")) for a in case["args"]]

    if case.get("correlation") == "marker":
        args.append(f"--headers={MARKER_HEADER}: {case['case_id']}")

    return [
        "docker",
        "run",
        "--rm",
        "--network",
        TOOL_NETWORK,
        TOOL_IMAGE,
        executable,
        *args,
    ]
