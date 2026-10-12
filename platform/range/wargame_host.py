from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from range.ports import RangeUnavailable

ROLE = "wargames"
COMPOSE = "wargames/{wargame}/compose.yaml"
SHIPPED = "deploy/wargame-host/wargames/{wargame}.yaml"
DAEMON = "deploy/wargame-host/daemon.json"
INSTALLED = "/opt/fsl/wargames/{wargame}.yaml"
TAG = re.compile(r"\$\{FSL_IMAGE_TAG(?::-[^}]*)?\}")
DROPPED = ("build", "networks")
UP_TIMEOUT = 900.0
SENSOR = "/opt/fsl/sensor.yaml"
SENSOR_PROJECT = "sensor"
SENSOR_INTERFACE = "FSL_SENSOR_INTERFACE"

def render(document: dict, tag: str, publish: dict[str, int]) -> str:
    services = {}
    for name, service in (document.get("services") or {}).items():
        kept = {key: value for key, value in service.items() if key not in DROPPED}
        kept["image"] = TAG.sub(tag, kept["image"])
        kept["container_name"] = name
        if name in publish:
            kept["ports"] = [f"{publish[name]}:{publish[name]}"]
        services[name] = kept
    return yaml.safe_dump({"services": services}, sort_keys=True)

def generated(source: Path, host: str, wargames, publish: dict[str, int], tag: str,
              mtu: int) -> dict[str, bytes]:
    if not tag:
        raise RangeUnavailable(
            f"{host} pulls the wargames' images at build time by the platform's own tag; "
            f"set FSL_IMAGE_TAG")
    if not mtu:
        raise RangeUnavailable(
            f"{host} gives its containers' networks the tenant MTU; set "
            f"FSL_OPENSTACK_MTU (network.mtu in cloud.yaml)")
    files, served = {}, set()
    for wargame in wargames:
        path = Path(source) / COMPOSE.format(wargame=wargame)
        if not path.is_file():
            raise RangeUnavailable(f"{host} runs {wargame!r} and {path} does not exist")
        document = yaml.safe_load(path.read_text()) or {}
        served |= set(document.get("services") or {})
        files[SHIPPED.format(wargame=wargame)] = render(document, tag, publish).encode()
    unserved = sorted(set(publish) - served)
    if unserved:
        raise RangeUnavailable(
            f"{host} publishes {', '.join(unserved)}, which none of its wargames runs")
    files[DAEMON] = json.dumps({
        "mtu": mtu,
        "default-network-opts": {"bridge": {"com.docker.network.driver.mtu": str(mtu)}},
    }, sort_keys=True).encode()
    return files

def up(wargame: str) -> list[str]:
    return ["sudo", "docker", "compose", "-p", wargame, "-f", INSTALLED.format(wargame=wargame),
            "up", "-d", "--wait", "--pull", "never"]

def inside(container: str, argv: list[str], reads_input: bool) -> list[str]:
    return ["sudo", "docker", "exec", *(["-i"] if reads_input else []), container, *argv]

def sensor_up(address: str) -> list[str]:
    interface = f"$(ip -o -4 addr show to {address} | awk '{{print $2}}')"
    return ["sh", "-c", f'sudo env {SENSOR_INTERFACE}="{interface}" docker compose '
                        f"-p {SENSOR_PROJECT} -f {SENSOR} up -d --wait --pull never"]
