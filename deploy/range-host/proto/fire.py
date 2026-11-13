from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from redteam import harness

@dataclass
class Ran:
    exit_code: int
    output: str

    @property
    def ok(self):
        return self.exit_code == 0

def launcher(kali):
    def launch(image, argv, timeout=600.0):
        done = subprocess.run(["docker", "exec", "-u", "kali", "-e", "HOME=/home/kali", "-w", "/home/kali", kali, *argv],
                              capture_output=True, text=True, errors="replace", timeout=timeout)
        return Ran(done.returncode, done.stdout + done.stderr)
    return launch

def main():
    slot, case_file, target, out = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    kali = f"s{slot}-kali"
    subprocess.run(["docker", "exec", kali, "/usr/local/sbin/set-origin", "5.188.10.10"], check=True)
    launch = launcher(kali)
    recorded = []
    began = time.monotonic()
    for case in harness.load_cases(case_file):
        case = dict(case)
        case.setdefault("case_id", str(uuid.uuid4()))
        case.setdefault("correlation", "marker")
        started = datetime.now(timezone.utc)
        t = time.monotonic()
        result = harness.fire(case, launch, target)
        ended = datetime.now(timezone.utc)
        recorded.append({key: case.get(key) for key in ("case_id", "name", "malicious", "correlation", "expect", "source_ip")}
                        | {"started_at": started.isoformat(), "ended_at": ended.isoformat(),
                           "seconds": round(time.monotonic() - t, 1), "exit_code": getattr(result, "exit_code", None)})
        print(f"{case['name']} {recorded[-1]['seconds']}s exit={recorded[-1]['exit_code']}", flush=True)
    Path(out).write_text(json.dumps(recorded, indent=1))
    print(f"total {time.monotonic() - began:.1f}s")

if __name__ == "__main__":
    main()
