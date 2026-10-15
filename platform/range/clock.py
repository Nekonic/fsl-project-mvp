from __future__ import annotations

import shlex

TIMESYNCD = "/etc/systemd/timesyncd.conf.d/60-fsl.conf"
FIRST_ANSWER = 30

def timesyncd(server: str) -> str:
    return f"[Time]\nNTP={server}\n"

def command(server: str) -> list[str]:
    return ["sh", "-c", (
        f"sudo install -d -m 0755 {TIMESYNCD.rsplit('/', 1)[0]} && "
        f"sudo tee {TIMESYNCD} >/dev/null && "
        "sudo systemctl restart systemd-timesyncd && "
        f"for _ in $(seq {FIRST_ANSWER}); do "
        f"[ \"$(timedatectl show-timesync -p ServerAddress --value)\" = {shlex.quote(server)} ] && "
        "[ -n \"$(timedatectl show-timesync -p NTPMessage --value)\" ] && exit 0; "
        "sleep 1; done; "
        f"echo \"no answer from {server} in {FIRST_ANSWER}s\" >&2; exit 1"
    )]
