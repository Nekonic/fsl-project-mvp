from __future__ import annotations

import base64
import json

from range import fabric
from range.declared import Declaration
from range.ports import RangeUnavailable, Segment

TEMPLATE = "deploy/pfsense/configure.php"
RULES = "deploy/suricata/rules/local.rules"
SESSION = "fsl-edge"
REPORTS = "fsl-edge "
HOLDS = "fsl-edge wan "
SENSING = "fsl-edge sensor "

def home(declaration: Declaration) -> list[str]:
    origins = [origin.subnet for origin in declaration.origins]
    return origins + [fabric.INSIDE["estate"], fabric.INSIDE[fabric.MANAGEMENT]]

def home_net(declaration: Declaration) -> str:
    return "[" + ",".join(home(declaration)) + "]"

def settings(segments: tuple[Segment, ...], declaration: Declaration, rules: str,
             collector: str) -> dict:
    origins = [segment for segment in segments if segment.outside]
    unrouted = [segment.id for segment in origins if not segment.gateway]
    if unrouted:
        raise RangeUnavailable(
            f"origins {', '.join(unrouted)} have no gateway address for the edge to hold"
        )
    gateways = [
        {"id": segment.id, "address": segment.gateway, "bits": segment.subnet.split("/")[1]}
        for segment in origins
    ]
    return {"wan": gateways[0], "aliases": gateways[1:], "home": home(declaration),
            "rules": rules, "collector": collector}

def playback(wanted: dict, template: str) -> str:
    blob = base64.b64encode(json.dumps(wanted).encode()).decode()
    return f"$fsl = json_decode(base64_decode('{blob}'), true);\n{template}"

def command() -> list[str]:
    return ["sh", "-c", f"cat > /etc/phpshellsessions/{SESSION} && "
                        f"/usr/local/sbin/pfSsh.php playback {SESSION}"]

def held(output: str) -> set[str]:
    return {
        address
        for line in output.splitlines() if line.startswith(HOLDS)
        for address in line[len(HOLDS):].split()
    }

def sensing(output: str) -> bool:
    return any(
        line.startswith(SENSING) and line.split()[-1] == "running"
        for line in output.splitlines()
    )

def reported(output: str) -> tuple[str, ...]:
    return tuple(
        line[len(REPORTS):] for line in output.splitlines() if line.startswith(REPORTS)
    )

def wan_rule_loaded(output: str) -> bool:
    return "wanrule 1" in reported(output)
