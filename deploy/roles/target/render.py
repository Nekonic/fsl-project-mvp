import argparse
import re
from pathlib import Path

import yaml

TAG = re.compile(r"\$\{CR_IMAGE_TAG(?::-[^}]*)?\}")
DROPPED = ("build",)
BACKEND = "backend"
FRONT = "front"


def address_variable(wargame: str) -> str:
    return f"{wargame.upper().replace('-', '_')}_ADDRESS"


def rendered(wargame: str, compose: dict, settings: dict, tag: str, mtu: int) -> dict:
    fronts = settings.get("fronts") or {}
    limits = settings.get("limits") or {}
    extra = settings.get("extra_hosts") or {}
    services = {}
    for name, service in (compose.get("services") or {}).items():
        kept = {key: value for key, value in service.items() if key not in DROPPED}
        kept["image"] = TAG.sub(tag, kept["image"])
        kept["container_name"] = name
        kept["hostname"] = name
        kept.update(settings.get("contained") or {})
        kept.update(limits.get(name) or {})
        if kept.get("healthcheck"):
            kept["healthcheck"] = {**kept["healthcheck"], **(settings.get("healthcheck") or {})}
        kept["networks"] = {BACKEND: {}}
        if name in fronts:
            port = fronts[name]
            variable = address_variable(wargame)
            kept["networks"][FRONT] = {}
            kept["ports"] = [f"${{{variable}:?the slot names the {wargame} address}}:{port}:{port}"]
        if extra.get(name):
            kept["extra_hosts"] = list(extra[name])
        services[name] = kept
    mtu_option = {"com.docker.network.driver.mtu": str(mtu)}
    networks = {BACKEND: {"internal": True, "driver_opts": {
        **mtu_option, "com.docker.network.bridge.gateway_mode_ipv4": "isolated"}}}
    if any(FRONT in service["networks"] for service in services.values()):
        networks[FRONT] = {"driver_opts": mtu_option}
    return {"name": wargame, "services": services, "networks": networks}


class Unaliased(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--mtu", type=int, required=True)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--into", type=Path, required=True)
    parser.add_argument("composes", type=Path, nargs="+")
    given = parser.parse_args()
    settings = yaml.safe_load(given.settings.read_text())
    for path in given.composes:
        wargame = path.stem
        document = rendered(wargame, yaml.safe_load(path.read_text()), settings, given.tag, given.mtu)
        written = given.into / wargame / "compose.yaml"
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_text(yaml.dump(document, Dumper=Unaliased, sort_keys=True))


if __name__ == "__main__":
    main()
