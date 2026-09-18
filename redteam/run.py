#!/usr/bin/env python
"""케이스 파일을 실행하고 세션 번호를 출력한다."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from redteam.harness import Harness, load_cases  # noqa: E402

DEFAULT_CASES = Path(__file__).resolve().parent / "cases" / "default.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(description="FSL 레드팀 하니스")
    parser.add_argument("--platform", default="http://localhost:8000")
    parser.add_argument("--target", default="http://localhost:8080")
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    args = parser.parse_args()

    cases = load_cases(args.cases)
    attacks = sum(1 for c in cases if c["malicious"])
    print(f"케이스 {len(cases)}건 (공격 {attacks}, 정상 {len(cases) - attacks})")

    if attacks == len(cases):
        print("경고: 정상 케이스가 없다. 오탐을 채점할 수 없다.", file=sys.stderr)

    session_id = Harness(args.platform, args.target).run(cases)

    print(f"세션 {session_id} 완료")
    print(f"  채점: curl -X POST {args.platform}/api/sessions/{session_id}/ingest/")
    print(f"        curl {args.platform}/api/sessions/{session_id}/score/")
    print(f"  콘솔: {args.platform}/  (세션 번호 {session_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
