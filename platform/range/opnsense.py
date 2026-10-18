from __future__ import annotations

import base64
import hashlib
import shlex
import uuid
import xml.etree.ElementTree as ElementTree

from range import fabric
from range.ports import RangeUnavailable, Segment

CONFIG = "deploy/opnsense/config.xml"
INCLUDE = "deploy/opnsense/suricata.yaml"
SCRIPT = "deploy/opnsense/configure.sh"
RULES = "deploy/suricata/rules/local.rules"
UPLOADS = "opnsense"
HOSTNAME = "edge"
IMAGE_SETTINGS = "fsl/opnsense.conf"
IMAGE_CONFIG = "fsl/config.xml"
IMAGE_PROPERTIES = {"hw_vif_model": "virtio", "hw_disk_bus": "virtio", "os_distro": "freebsd",
                    "min_ram": 3072}
STAGED = {"config": "/tmp/fsl-config.xml", "include": "/tmp/fsl-suricata.yaml",
          "rules": "/tmp/fsl.rules"}
INSTALLED = {"config": "/conf/config.xml", "include": "/usr/local/etc/suricata/conf.d/fsl.yaml",
             "rules": "/usr/local/etc/suricata/rules/fsl.rules"}
SETTLED = "/conf/fsl-settled"
SOCKET = "/var/run/suricata-command.socket"
SENSOR_ANSWER = 60
WAN = "vtnet0"
REPORTS = "fsl-edge "
HOLDS = "fsl-edge wan "
SENSING = "fsl-edge sensor "
BOOTED = "fsl-edge booted "
REBOOTING = "fsl-edge rebooting"
RESET = "fsl-edge reset"
DRIFTED = "fsl-edge drifted"
INTERFACES = ("wan", "lan", "opt1")
MANAGEMENT_INTERFACE = "opt1"
NAMESPACE = uuid.UUID("6f1c7e3a-5d0b-4c8e-9a51-2b7d4e0f9c11")
LEVELS = "info,notice,warn,err,crit,alert,emerg"
FRONT_PORT = "80"


def home(inside: dict[str, str]) -> list[str]:
    return [inside["estate"], inside[fabric.MANAGEMENT]]


def _gateway(segment: Segment) -> dict:
    return {"id": segment.id, "address": segment.gateway, "bits": segment.subnet.split("/")[1]}


def settings(segments: tuple[Segment, ...], collector: tuple[str, int],
             inside: dict[str, str], mtu: int, public_key: str, management: str = "",
             front: str = "", hostname: str = "", clock: str = "") -> dict:
    origins = [segment for segment in segments if segment.outside]
    unrouted = [segment.id for segment in origins if not segment.gateway]
    if unrouted:
        raise RangeUnavailable(
            f"origins {', '.join(unrouted)} have no gateway address for the edge to hold"
        )
    if not origins:
        raise RangeUnavailable("the range has no origin, so the edge has no address to hold")
    estate = next((s for s in segments if s.id == "estate" and s.gateway), None)
    if estate is None:
        raise RangeUnavailable("the estate has no gateway address for the edge to hold")
    if not mtu:
        raise RangeUnavailable("the edge needs the tenant networks' MTU; set network.mtu in cloud.yaml")
    if not public_key:
        raise RangeUnavailable("the platform has no public key for the edge to trust yet; build the fabric first")
    gateways = [_gateway(segment) for segment in origins]
    wanted = {"wan": gateways[0], "aliases": gateways[1:], "lan": _gateway(estate),
              "home": home(inside), "collector": {"host": collector[0], "port": collector[1]},
              "mtu": mtu, "key": public_key}
    mgmt = next((s for s in segments if s.id == fabric.MANAGEMENT and s.subnet), None)
    if management and mgmt is not None:
        wanted["mgmt"] = {"id": mgmt.id, "address": management, "bits": mgmt.subnet.split("/")[1]}
    if front:
        wanted["front"] = front
    if hostname:
        wanted["hostname"] = hostname
    if clock:
        wanted["clock"] = clock
    return wanted


def _set(parent, path: str, text: str):
    node = parent
    for name in path.split("/"):
        found = node.find(name)
        node = found if found is not None else ElementTree.SubElement(node, name)
    node.text = text
    return node


def _vip(parent, alias: dict):
    vip = ElementTree.SubElement(
        parent, "vip", uuid=str(uuid.uuid5(NAMESPACE, f"vip {alias['id']}")))
    for name, text in (("interface", "wan"), ("mode", "ipalias"), ("type", "single"),
                       ("subnet", alias["address"]), ("subnet_bits", alias["bits"]),
                       ("descr", f"fsl origin {alias['id']}")):
        _set(vip, name, text)


def _destination(parent, collector: dict):
    destination = ElementTree.SubElement(
        parent, "destination", uuid=str(uuid.uuid5(NAMESPACE, "collector")))
    for name, text in (("enabled", "1"), ("transport", "udp4"), ("program", ""),
                       ("level", LEVELS), ("facility", ""), ("hostname", collector["host"]),
                       ("port", str(collector["port"])), ("rfc5424", "1"),
                       ("description", "fsl collector")):
        _set(destination, name, text)


def _front_only(root, front: str):
    crossing = next(rule for rule in root.findall("filter/rule")
                    if rule.findtext("interface") == "wan" and rule.findtext("type") == "pass")
    _set(crossing, "protocol", "tcp")
    destination = crossing.find("destination")
    for held in list(destination):
        destination.remove(held)
    _set(destination, "address", front)
    _set(destination, "port", FRONT_PORT)


def render(template: str, wanted: dict) -> str:
    root = ElementTree.fromstring(template)
    root_user = next(user for user in root.findall("system/user")
                     if user.findtext("name") == "root")
    _set(root_user, "authorizedkeys", base64.b64encode(wanted["key"].encode()).decode())
    if wanted.get("hostname"):
        _set(root, "system/hostname", wanted["hostname"])
    for interface in INTERFACES:
        _set(root, f"interfaces/{interface}/mtu", str(wanted["mtu"]))
    for interface, held in (("wan", wanted.get("wan")), ("lan", wanted.get("lan")),
                            (MANAGEMENT_INTERFACE, wanted.get("mgmt"))):
        if held:
            _set(root, f"interfaces/{interface}/ipaddr", held["address"])
            _set(root, f"interfaces/{interface}/subnet", held["bits"])
    virtual = root.find("virtualip")
    for alias in wanted.get("aliases") or []:
        _vip(virtual, alias)
    _set(root, "OPNsense/IDS/general/homenet", ",".join(wanted.get("home") or []))
    if wanted.get("collector"):
        _destination(root.find("OPNsense/Syslog/destinations"), wanted["collector"])
    if wanted.get("front"):
        _front_only(root, wanted["front"])
    if wanted.get("clock"):
        _set(root, "system/timeservers", wanted["clock"])
        _set(root, "ntpd/iburst", wanted["clock"])
        if wanted.get("mgmt"):
            _set(root, "ntpd/interface", MANAGEMENT_INTERFACE)
    ElementTree.indent(root)
    return '<?xml version="1.0"?>\n' + ElementTree.tostring(root, encoding="unicode") + "\n"


def _heredoc(path: str, content: str) -> str:
    marker = "FSL_" + uuid.uuid5(NAMESPACE, content).hex.upper()
    if marker in content:
        raise RangeUnavailable(f"{path} holds its own end marker")
    return f"cat > {path} <<'{marker}'\n{content}{'' if content.endswith(chr(10)) else chr(10)}{marker}\n"


def playback(config: str, include: str, rules: str, script: str) -> str:
    return "".join((
        _heredoc(STAGED["config"], config),
        _heredoc(STAGED["include"], include),
        _heredoc(STAGED["rules"], rules),
        script,
    ))


def command() -> list[str]:
    return ["sh"]


def fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def record(config: str) -> list[str]:
    return ["sh", "-c", f"echo \"{fingerprint(config)} $(sha256 -q {INSTALLED['config']})\" "
                        f"> {SETTLED}"]


def _flushes(subnets: list[str]) -> str:
    return "".join(
        f"/sbin/pfctl -k {subnet} >/dev/null 2>&1\n"
        f"/sbin/pfctl -k 0.0.0.0/0 -k {subnet} >/dev/null 2>&1\n"
        for subnet in subnets
    )


def in_place(config: str, include: str, rules: str, subnets: list[str]) -> str:
    return _heredoc(STAGED["rules"], rules) + (
        "set -eu\n"
        f"install -m 0644 {STAGED['rules']} {INSTALLED['rules']}\n"
        f"rm -f {STAGED['rules']}\n"
        "drift=''\n"
        f"[ \"$(cat {SETTLED} 2>/dev/null)\" = "
        f"\"{fingerprint(config)} $(sha256 -q {INSTALLED['config']} 2>/dev/null)\" ] "
        "|| drift=\"$drift config\"\n"
        f"[ \"$(sha256 -q {INSTALLED['include']} 2>/dev/null)\" = \"{fingerprint(include)}\" ] "
        "|| drift=\"$drift include\"\n"
        f"[ \"$(sha256 -q {INSTALLED['rules']} 2>/dev/null)\" = \"{fingerprint(rules)}\" ] "
        "|| drift=\"$drift rules\"\n"
        f"if [ -n \"$drift\" ]; then echo \"{DRIFTED}$drift\"; exit 0; fi\n"
        f"{_flushes(subnets)}"
        "/usr/local/sbin/configctl filter reload >/dev/null\n"
        "/usr/local/sbin/configctl ids restart >/dev/null\n"
        "tries=0\n"
        f"until /usr/local/bin/suricatasc -c uptime {SOCKET} >/dev/null 2>&1; do\n"
        "  tries=$((tries + 1))\n"
        f"  if [ \"$tries\" -ge {SENSOR_ANSWER} ]; then echo \"{DRIFTED} sensor\"; exit 0; fi\n"
        "  sleep 1\n"
        "done\n"
        f"echo \"{RESET}\"\n"
    )


def drifted(output: str) -> tuple[str, ...]:
    return next((tuple(line[len(DRIFTED):].split()) for line in output.splitlines()
                 if line.startswith(DRIFTED)), ())


def reset_done(output: str) -> bool:
    return RESET in output.splitlines()


def verify() -> list[str]:
    return ["sh", "-c", (
        f"echo \"{BOOTED}$(sysctl -n kern.boottime | sed 's/.*sec = \\([0-9]*\\),.*/\\1/')\"; "
        f"echo \"{HOLDS}$(ifconfig {WAN} inet | awk '/inet /{{printf \"%s \", $2}}')\"; "
        f"if pgrep -q -x suricata; then echo '{SENSING}{WAN} running'; "
        f"else echo '{SENSING}{WAN} stopped'; fi; "
        "php -r '$c = simplexml_load_file(\"/conf/config.xml\"); "
        "foreach ($c->OPNsense->Syslog->destinations->destination as $d) "
        "{ if ((string)$d->enabled === \"1\") echo \"fsl-edge logs \", $d->hostname, \":\", $d->port, \"\\n\"; }'; "
        f"echo \"fsl-edge wanrule $(pfctl -sr 2>/dev/null | grep -c 'pass in quick on {WAN} inet ')\""
    )]


def booted(output: str) -> str:
    return next((line[len(BOOTED):].strip() for line in output.splitlines()
                 if line.startswith(BOOTED)), "")


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
    return any(
        line.startswith("fsl-edge wanrule ") and line.split()[-1].isdigit()
        and int(line.split()[-1]) > 0
        for line in output.splitlines()
    )


def image_bundle(template: str, release, mtu: int, public_key: str) -> dict[str, bytes]:
    settings = {"VERSION": release.version, "MIRROR": release.mirror.rstrip("/"),
                "NANO": release.nano, "IMAGE_SHA256": release.image_sha256,
                "PUBKEY_SHA256": release.pubkey_sha256}
    return {
        IMAGE_SETTINGS: "".join(f"{name}={shlex.quote(value)}\n" for name, value in settings.items()).encode(),
        IMAGE_CONFIG: render(template, {"mtu": mtu, "key": public_key}).encode(),
    }
