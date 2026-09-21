"""The shape of the range, read off the range itself.

A drawing of a network is wrong within a session. An address changes, a
segment is added, a sensor moves - and the picture keeps saying what was true
last week, which is worse than no picture, because it is believed. Docker
already knows all of it, so this asks rather than remembers.

Two things it knows that nothing else does. A container on both an outside
segment and an inside one is a way in, by shape rather than by policy - so
that is a fact about the topology and not a caption on it. And a sensor that
shares another container's network namespace is on no network of its own, so
anything reading only networks draws a range with no IDS in it.
"""

from __future__ import annotations

import json
import subprocess

from django.conf import settings

_TIMEOUT = 30

# Compose stamps this on everything it creates, which is how the stack's own
# networks are told from whatever else is running on the host.
PROJECT_LABEL = "com.docker.compose.project"

# A network carrying this is somewhere an attack comes from. See attacker.py.
ORIGIN_LABEL = "fsl.origin"

# What to call the segment on screen. Without it the diagram shows compose's
# own network names - `edge-br`, `mgmt` - which say nothing to anyone who did
# not write the compose file, and the first person to read it asked what they
# were.
NAME_LABEL = "fsl.segment"


class StackUnavailable(RuntimeError):
    """Docker cannot be reached, so the shape cannot be read."""


def _docker(argv: list[str]) -> str:
    result = subprocess.run(
        ["docker", *argv], capture_output=True, text=True, timeout=_TIMEOUT,
    )
    if result.returncode != 0:
        raise StackUnavailable(
            f"docker {' '.join(argv[:2])}: {result.stderr.strip()[:200]} "
            f"The shape of the stack can only be read from the stack."
        )
    return result.stdout


def _project() -> str:
    """The compose project, taken from a network name rather than an env var.

    The same rule attacker.py uses: one place decides what the prefix is, and
    it is the stack that is running, not a setting that might disagree with it.
    """
    return settings.ATTACKER_NETWORK.split("_", 1)[0]


def _namespaces() -> dict[str, str]:
    """Each container's network mode, which says whose namespace it is in."""
    names = [
        line.strip()
        for line in _docker([
            "ps", "--filter", f"label={PROJECT_LABEL}={_project()}",
            "--format", "{{.Names}}",
        ]).splitlines()
        if line.strip()
    ]
    if not names:
        raise StackUnavailable(f"nothing of project {_project()!r} is running")

    modes = {}
    for line in _docker([
        "container", "inspect", "--format", "{{.Name}} {{.HostConfig.NetworkMode}}",
        *names,
    ]).splitlines():
        name, _, mode = line.strip().partition(" ")
        if name:
            modes[name.lstrip("/")] = mode
    return modes


def shape() -> dict:
    """Segments, what sits on them, and which boxes cross between them."""
    names = [
        line.strip()
        for line in _docker([
            "network", "ls", "--filter", f"label={PROJECT_LABEL}={_project()}",
            "--format", "{{.Name}}",
        ]).splitlines()
        if line.strip()
    ]
    if not names:
        raise StackUnavailable(f"project {_project()!r} has no networks")

    networks = [
        json.loads(line)
        for line in _docker(
            ["network", "inspect", "--format", "{{json .}}", *names]
        ).splitlines()
    ]

    # An id is a container id here, but every network reports the same one, so
    # it is also how a shared namespace is resolved back to a name.
    named = {
        container_id: attached["Name"]
        for network in networks
        for container_id, attached in (network.get("Containers") or {}).items()
    }

    sensors, watching = [], {}
    for name, mode in _namespaces().items():
        if not mode.startswith("container:"):
            continue
        host = named.get(mode.split(":", 1)[1])
        if not host:
            continue
        sensors.append({"name": name, "watches": host})
        watching[host] = name

    # Which side of the range each box has a foot on. Counting segments
    # instead would call the proxy a crossing for being on four origins,
    # which are all outside - and then the one number that matters, how many
    # ways in there are past the WAF, would be buried in boxes that are not.
    sides: dict[str, set[bool]] = {}
    for network in networks:
        outside = bool((network.get("Labels") or {}).get(ORIGIN_LABEL))
        for attached in (network.get("Containers") or {}).values():
            sides.setdefault(attached["Name"], set()).add(outside)

    segments = []
    for network in networks:
        config = (network.get("IPAM") or {}).get("Config") or [{}]
        nodes = [
            {
                "name": attached["Name"],
                "address": attached.get("IPv4Address", "").split("/")[0],
                # A foot on each side of the range: the whole of what this
                # picture is for. Every box with this flag is a way in, and
                # the defence is only not optional while the WAF is the one
                # that carries it.
                "crosses": sides.get(attached["Name"]) == {True, False},
                "sensor": watching.get(attached["Name"], ""),
            }
            for attached in (network.get("Containers") or {}).values()
        ]
        labels = network.get("Labels") or {}
        label = labels.get(ORIGIN_LABEL, "")
        segments.append({
            "id": network["Name"].split("_", 1)[-1],
            "name": labels.get(NAME_LABEL, "") or network["Name"].split("_", 1)[-1],
            "network": network["Name"],
            "subnet": config[0].get("Subnet", ""),
            "gateway": config[0].get("Gateway", ""),
            "outside": bool(label),
            "label": label,
            "nodes": sorted(nodes, key=lambda node: node["name"]),
            # Whether anything is listening on this segment at all. A segment
            # with no sensor is a place attacks arrive and nothing is seen.
            "sensor": next((n["sensor"] for n in nodes if n["sensor"]), ""),
        })

    # Outside first: that is the direction an attack travels, and reading the
    # picture in any other order says nothing about what protects what.
    return {
        "segments": sorted(
            segments, key=lambda s: (not s["outside"], s["id"])
        ),
        "sensors": sorted(sensors, key=lambda s: s["name"]),
    }
