from __future__ import annotations

import base64
import json

from range import fabric
from range.declared import Declaration
from range.ports import RangeUnavailable, Segment

TEMPLATE = "deploy/pfsense/configure.php"
SESSION = "fsl-edge"
HOLDS = "fsl-edge wan "

def home_net(declaration: Declaration) -> str:
    origins = [origin.subnet for origin in declaration.origins]
    inside = [fabric.INSIDE["estate"], fabric.INSIDE[fabric.MANAGEMENT]]
    return "[" + ",".join(origins + inside) + "]"

def settings(segments: tuple[Segment, ...]) -> dict:
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
    return {"wan": gateways[0], "aliases": gateways[1:]}

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
