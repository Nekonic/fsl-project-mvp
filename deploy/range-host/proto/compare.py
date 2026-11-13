from __future__ import annotations

import json
import sys

FIELDS = ("verdict", "corroborated", "sids", "alert_sources", "http_sources")

def keyed(path):
    return {row["name"]: row for row in json.load(open(path))}

def main():
    base, proto = keyed(sys.argv[1]), keyed(sys.argv[2])
    ignore = set(sys.argv[3:])
    differences = 0
    for name in base:
        b, p = base[name], proto.get(name)
        if p is None:
            print(f"MISSING {name}"); differences += 1; continue
        for field in FIELDS:
            bv, pv = b[field], p[field]
            if field == "http_sources":
                bv = {k: v for k, v in bv.items() if k not in ignore}
                pv = {k: v for k, v in pv.items() if k not in ignore}
            if bv != pv:
                differences += 1
                print(f"DIFF {name} {field}\n  base  {bv}\n  proto {pv}")
        print(f"{'same' if all(b[f] == p[f] or f == 'http_sources' for f in FIELDS) else 'DIFF':4} {name} {b['verdict']}/{p['verdict']} counts base {b['counts']} proto {p['counts']}")
    print(f"{differences} differences")

if __name__ == "__main__":
    main()
