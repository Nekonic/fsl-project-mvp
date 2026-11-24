from __future__ import annotations

import copy

WAF_FILES = {"/etc/nginx/modsecurity/crs/crs-setup.conf": "SecDefaultAction \"phase:1,log,auditlog,pass\"\n"}

ROUND = {
    "problem": {"kind": "round", "wargame": "board", "side": "defence", "title": "Placeholder round",
                "summary": "Placeholder summary", "body": "Placeholder body", "published": False},
    "round": {"matchups": ["pvp", "def_vs_bot"], "posture": "placeholder start", "probe_cases": [],
              "objectives": ["board-auth-user-admin"], "traffic": None, "benign_every_s": 30,
              "time_limit_s": 900, "bot_steps": [], "cards": []},
    "start_posture": {"name": "placeholder start", "suricata_rules": "", "waf_files": WAF_FILES},
}


def round_problem(problem: dict | None = None, **setup) -> dict:
    made = copy.deepcopy(ROUND)
    made["problem"].update(problem or {})
    made["round"].update(setup)
    return made


def posture(**fields) -> dict:
    return {"wargame": "board", "name": "placeholder posture", "suricata_rules": "",
            "waf_files": copy.deepcopy(WAF_FILES), **fields}
