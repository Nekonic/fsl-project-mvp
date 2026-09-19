"""The attacker's box: where free-form traffic comes from.

Window correlation matches alerts by source IP, so labelling anything typed in
the terminal means knowing the address Suricata will see for it. That is the
Kali container's address on the stack network, and only Docker can answer it.
"""

from __future__ import annotations

import json
import subprocess

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
            "docker", "inspect", settings.ATTACKER_CONTAINER,
            "--format", "{{json .NetworkSettings.Networks}}",
        ],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
    )
    if result.returncode != 0:
        raise AttackerUnavailable(
            f"{settings.ATTACKER_CONTAINER}: {result.stderr.strip()[:200]} "
            f"Start it with: docker compose up -d kali"
        )

    networks = json.loads(result.stdout or "{}")
    address = (networks.get(settings.ATTACKER_NETWORK) or {}).get("IPAddress")
    if not address:
        raise AttackerUnavailable(
            f"{settings.ATTACKER_CONTAINER} has no address on "
            f"{settings.ATTACKER_NETWORK}; it is on {sorted(networks)}"
        )
    return address
