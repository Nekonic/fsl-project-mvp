from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

def lines(path):
    if not path.exists():
        return
    with open(path, errors="replace") as found:
        for line in found:
            line = line.strip()
            if line.startswith("{"):
                yield json.loads(line)

def main():
    slot_dir, out = Path(sys.argv[1]), sys.argv[2]
    n = 0
    with gzip.open(out, "wt") as written:
        for leg, name in (("edge-log", "edge"), ("estate-log", "wargame-host")):
            for position, doc in enumerate(lines(slot_dir / leg / "eve.json")):
                if doc.get("event_type") not in ("alert", "http"):
                    continue
                doc["event"] = {"module": "suricata"}
                doc["log"] = {"syslog": {"hostname": name}}
                written.write(json.dumps([f"{name}-{position}", doc]) + "\n"); n += 1
        for position, doc in enumerate(lines(slot_dir / "waf" / "audit.log")):
            doc["event"] = {"module": "modsecurity"}
            doc["log"] = {"syslog": {"hostname": "waf"}}
            written.write(json.dumps([f"waf-{position}", doc]) + "\n"); n += 1
    print(f"{n} docs")

if __name__ == "__main__":
    main()
