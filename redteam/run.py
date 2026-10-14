from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "platform"))

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fsl.settings")
django.setup()

import requests
from django.conf import settings

from api.models import Session
from range import substrate
from wargames import WARGAMES
from redteam import harness

DEFAULT_CASES = Path(__file__).resolve().parent / "cases" / "board.yaml"

def range_of(adapter, session_id):
    if hasattr(adapter, "for_session"):
        return adapter.for_session(session_id)
    if hasattr(adapter, "in_slot"):
        return adapter.in_slot(Session.objects.get(pk=session_id).slot or 1)
    return adapter

def main() -> int:
    parser = argparse.ArgumentParser(description="FSL red team harness")
    parser.add_argument("--platform", default="http://localhost:8000")
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument(
        "--tool-target",
        default=harness.DEFAULT_TOOL_TARGET,
        help="address the tool containers use for the target inside the stack",
    )
    args = parser.parse_args()

    adapter = substrate()
    bound = {}

    def opened(session_id):
        session_range = range_of(adapter, session_id)
        bound["launch"] = session_range.launcher(settings.RANGE.default_origin)
        print(f"session {session_id} opened", flush=True)

    def launch(image, argv, timeout=600.0):
        return bound["launch"](image, argv, timeout=timeout)

    case_file = Path(args.cases).name
    scenario = next(
        (key for key, wargame in WARGAMES.items() if wargame["case_file"] == case_file),
        "board",
    )

    cases = harness.load_cases(args.cases)
    attacks = sum(1 for c in cases if c["malicious"])
    print(f"{len(cases)} cases ({attacks} attack, {len(cases) - attacks} benign)")

    if attacks == len(cases):
        print("warning: no benign cases, false positives cannot be scored", file=sys.stderr)

    try:
        session_id = harness.run(
            cases, args.platform, launch, args.tool_target, scenario,
            announce=opened,
        )
    except requests.HTTPError as refused:
        print(f"{refused}: {refused.response.text}", file=sys.stderr)
        return 1

    print(f"session {session_id} done")
    print(f"  score:   curl -X POST {args.platform}/api/sessions/{session_id}/ingest/")
    print(f"           curl {args.platform}/api/sessions/{session_id}/score/")
    print(f"  console: {args.platform}/  (session {session_id})")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
