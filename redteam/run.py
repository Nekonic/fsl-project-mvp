#!/usr/bin/env python
"""Run a case file and print the session number."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from redteam.harness import (  # noqa: E402
    DEFAULT_TOOL_TARGET,
    Harness,
    load_cases,
)

DEFAULT_CASES = Path(__file__).resolve().parent / "cases" / "default.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(description="FSL red team harness")
    parser.add_argument("--platform", default="http://localhost:8000")
    parser.add_argument("--target", default="http://localhost:8080")
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument(
        "--tool-target",
        default=DEFAULT_TOOL_TARGET,
        help="address the tool containers use for the target inside the stack",
    )
    args = parser.parse_args()

    cases = load_cases(args.cases)
    attacks = sum(1 for c in cases if c["malicious"])
    print(f"{len(cases)} cases ({attacks} attack, {len(cases) - attacks} benign)")

    if attacks == len(cases):
        print("warning: no benign cases, false positives cannot be scored", file=sys.stderr)

    session_id = Harness(
        args.platform, args.target, tool_target_url=args.tool_target
    ).run(cases)

    print(f"session {session_id} done")
    print(f"  score:   curl -X POST {args.platform}/api/sessions/{session_id}/ingest/")
    print(f"           curl {args.platform}/api/sessions/{session_id}/score/")
    print(f"  console: {args.platform}/  (session {session_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
