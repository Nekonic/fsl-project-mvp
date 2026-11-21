from __future__ import annotations

import copy

HP = {"budget": 100, "per_request": 1, "refused_x": 3, "burst_per_s": 5, "burst_x": 2}
TUNING = {"paranoia": 2, "exclusions": []}

ROUND = {
    "problem": {"kind": "round", "wargame": "board", "side": "defence", "title": "Placeholder round",
                "summary": "Placeholder summary", "body": "Placeholder body", "published": False},
    "round": {"matchups": ["pvp", "def_vs_bot"], "posture": "placeholder start", "probe_cases": [],
              "objectives": ["board-auth-user-admin"], "hp": HP, "traffic": None, "benign_every_s": 30,
              "time_limit_s": 900},
    "start_posture": {"name": "placeholder start", "suricata_rules": "", "crs_tuning": TUNING},
}


def round_problem(problem: dict | None = None, **setup) -> dict:
    made = copy.deepcopy(ROUND)
    made["problem"].update(problem or {})
    made["round"].update(setup)
    return made


def posture(**fields) -> dict:
    return {"wargame": "board", "name": "placeholder posture", "suricata_rules": "",
            "crs_tuning": copy.deepcopy(TUNING), **fields}
