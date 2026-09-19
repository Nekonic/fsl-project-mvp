"""The attacker's box: where free-form traffic comes from, and what marks it.

Window correlation matches alerts by source IP, so labelling anything typed in
the terminal means knowing the address Suricata will see. That is *not* the
Kali container's address: the terminal's traffic goes through the stamping
proxy, so the WAF - and the IDS inside its namespace - sees the proxy. Ask
Docker for the container whose address the alerts will actually carry.

The same proxy stamps the case marker, which it reads from a file this module
writes. That is what lets one piece of free-form traffic be scored both ways.
"""

from __future__ import annotations

import json
import subprocess

from pathlib import Path

from django.conf import settings

_TIMEOUT = 30


class AttackerUnavailable(RuntimeError):
    """The attacker container is not running, or Docker cannot be reached."""


def source_ip() -> str:
    """The address alerts from the terminal will carry.

    Never guessed. A wrong address matches no alert at all, which scores a
    real attack as a miss and blames the defence for it.
    """
    result = subprocess.run(
        [
            "docker", "inspect", settings.ATTACKER_SOURCE_CONTAINER,
            "--format", "{{json .NetworkSettings.Networks}}",
        ],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
    )
    if result.returncode != 0:
        raise AttackerUnavailable(
            f"{settings.ATTACKER_SOURCE_CONTAINER}: {result.stderr.strip()[:200]} "
            f"Start it with: docker compose up -d kali proxy"
        )

    networks = json.loads(result.stdout or "{}")
    address = (networks.get(settings.ATTACKER_NETWORK) or {}).get("IPAddress")
    if not address:
        raise AttackerUnavailable(
            f"{settings.ATTACKER_SOURCE_CONTAINER} has no address on "
            f"{settings.ATTACKER_NETWORK}; it is on {sorted(networks)}"
        )
    return address


def set_label(case_id: str | None) -> None:
    """Tell the proxy which marker to stamp, or to stop stamping.

    Written as a file rather than pushed over an API: the proxy reads it per
    request, so it needs no endpoint of its own and nothing to restart.
    """
    path = Path(settings.ATTACKER_LABEL_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(case_id or "")
