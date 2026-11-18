from __future__ import annotations

TIMESYNCD = "/etc/systemd/timesyncd.conf.d/60-cr.conf"

def timesyncd(server: str) -> str:
    return f"[Time]\nNTP={server}\n"
