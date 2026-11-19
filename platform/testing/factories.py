from __future__ import annotations

import copy

HP = {"budget": 100, "per_request": 1, "refused_x": 3, "burst_per_s": 5, "burst_x": 2}
TUNING = {"paranoia": 2, "exclusions": []}

LESSON = {
    "problem": {"kind": "lesson", "wargame": "board", "side": "defence", "title": "Placeholder lesson",
                "summary": "Placeholder summary", "body": "Placeholder body", "published": True},
    "steps": [
        {"order": 1, "body": "Placeholder step one", "opens": "kibana",
         "check": {"kind": "answer", "params": {"accept": ["placeholder answer"]}}, "answer": "placeholder answer",
         "hints": ["first placeholder hint", "second placeholder hint"]},
        {"order": 2, "body": "Placeholder step two", "opens": "ids_rules",
         "check": {"kind": "choice", "params": {"options": ["left", "right"], "correct": "right"}}, "hints": []},
        {"order": 3, "body": "Placeholder step three", "opens": "ids_rules",
         "check": {"kind": "rule_test", "params": {"engine": "ids", "case": "board-sqli-search"}}},
    ],
    "round": None,
    "start_posture": {"name": "placeholder start", "suricata_rules": "", "crs_tuning": TUNING},
}

ROUND = {
    "problem": {"kind": "round", "wargame": "board", "side": "defence", "title": "Placeholder round",
                "summary": "Placeholder summary", "body": "Placeholder body", "published": False},
    "steps": [],
    "round": {"matchups": ["pvp", "def_vs_bot"], "posture": "placeholder start", "probe_cases": [],
              "objectives": ["board-auth-user-admin"], "hp": HP, "traffic": None, "benign_every_s": 30,
              "time_limit_s": 900},
    "start_posture": {"name": "placeholder start", "suricata_rules": "", "crs_tuning": TUNING},
}


def lesson(**problem) -> dict:
    made = copy.deepcopy(LESSON)
    made["problem"].update(problem)
    return made


def round_problem(**setup) -> dict:
    made = copy.deepcopy(ROUND)
    made["round"].update(setup)
    return made


def posture(**fields) -> dict:
    return {"wargame": "board", "name": "placeholder posture", "suricata_rules": "",
            "crs_tuning": copy.deepcopy(TUNING), **fields}
