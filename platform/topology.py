from __future__ import annotations

import json
import subprocess

from django.conf import settings

_TIMEOUT = 30

                                                                            
                                                              
PROJECT_LABEL = "com.docker.compose.project"

                                                                             
ORIGIN_LABEL = "fsl.origin"

                                                                            
                                                                             
                                                                             
       
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
    return settings.ATTACKER_NETWORK.split("_", 1)[0]

def _namespaces() -> dict[str, str]:
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
                                                                             
                                                                           
            "sensor": next((n["sensor"] for n in nodes if n["sensor"]), ""),
        })

                                                                             
                                                                       
    return {
        "segments": sorted(
            segments, key=lambda s: (not s["outside"], s["id"])
        ),
        "sensors": sorted(sensors, key=lambda s: s["name"]),
    }
