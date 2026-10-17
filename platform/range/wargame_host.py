from __future__ import annotations

import json
import re
import shlex
import subprocess
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
SENSOR_CONFIG = "/opt/fsl/suricata.yaml"
SENSOR_CONFIG_SOURCE = "deploy/suricata/suricata.yaml"
SENSOR_PROJECT = "sensor"
SENSOR_INTERFACE = "FSL_SENSOR_INTERFACE"
BASELINE_RULES = "deploy/suricata/rules/local.rules"
LOG_READER_STATE = "/var/spool/rsyslog/imfile-state:*"
STOP_GRACE = 1
REGISTRY = "ghcr.io/nekonic/fsl-"
LOADED = "deploy/wargame-host/loaded"
SERVED_AT = "http://{address}:8000/api/range/images/sideloaded/{name}/"

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

def sideloaded_images(source: Path, wargames, tag: str, sideloaded) -> dict[str, str]:
    found = {}
    composes = [Path(source) / COMPOSE.format(wargame=wargame) for wargame in wargames] if sideloaded else []
    for path in (path for path in composes if path.is_file()):
        document = yaml.safe_load(path.read_text()) or {}
        for service in (document.get("services") or {}).values():
            image = TAG.sub(tag, service.get("image") or "")
            found.update({name: image for name in sideloaded if image == f"{REGISTRY}{name}:{tag}"})
    return found

def local_image_id(image: str, run=subprocess.run) -> str:
    done = run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
               capture_output=True, text=True)
    if done.returncode != 0 or not done.stdout.strip():
        raise RangeUnavailable(
            f"FSL_SIDELOADED names {image} and the platform's docker holds no such image: "
            f"{done.stderr.strip()[:200]}")
    return done.stdout.strip()

def saved(image: str) -> list[str]:
    return ["docker", "save", image]

def generated(source: Path, host: str, wargames, publish: dict[str, int], tag: str,
              mtu: int, loaded=()) -> dict[str, bytes]:
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
    if loaded:
        files[LOADED] = "".join(f"{image} {ident} {url}\n" for image, ident, url in sorted(loaded)).encode()
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
    return ["sh", "-c", f"sudo tee {SENSOR_CONFIG} >/dev/null && "
                        f'sudo env {SENSOR_INTERFACE}="{interface}" docker compose '
                        f"-p {SENSOR_PROJECT} -f {SENSOR} up -d --wait --pull never"]

def cleared(wargames, logs, sensed: bool) -> list[str]:
    steps = ["set -e", *(["systemctl stop rsyslog"] if logs else [])]
    steps += [f"docker compose -p {wargame} -f {INSTALLED.format(wargame=wargame)} "
              f"down -v --remove-orphans --timeout {STOP_GRACE}" for wargame in wargames]
    if sensed:
        steps.append(f"{SENSOR_INTERFACE}=lo docker compose -p {SENSOR_PROJECT} -f {SENSOR} "
                     f"down -v --timeout {STOP_GRACE}")
    if logs:
        steps.append(" ".join(["rm -f", *(shlex.quote(path) for path in logs), LOG_READER_STATE]))
    return ["sudo", "sh", "-c", "\n".join(steps)]
