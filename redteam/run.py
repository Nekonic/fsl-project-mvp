                     

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "platform"))

from range import declared              
from range.docker import Docker              
from redteam import harness              
from redteam.harness import DEFAULT_TOOL_TARGET, load_cases              

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
    parser.add_argument("--origin", default="")
    args = parser.parse_args()

    declaration = declared.read()
    launch = Docker(declaration).launcher(args.origin or declaration.default_origin)

    cases = load_cases(args.cases)
    attacks = sum(1 for c in cases if c["malicious"])
    print(f"{len(cases)} cases ({attacks} attack, {len(cases) - attacks} benign)")

    if attacks == len(cases):
        print("warning: no benign cases, false positives cannot be scored", file=sys.stderr)

    session_id = harness.run(
        cases, args.platform, args.target, launch, args.tool_target
    )

    print(f"session {session_id} done")
    print(f"  score:   curl -X POST {args.platform}/api/sessions/{session_id}/ingest/")
    print(f"           curl {args.platform}/api/sessions/{session_id}/score/")
    print(f"  console: {args.platform}/  (session {session_id})")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
