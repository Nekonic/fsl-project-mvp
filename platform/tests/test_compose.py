import pathlib
import re

import yaml

COMPOSE = pathlib.Path(__file__).resolve().parent.parent.parent / "compose.yaml"

def images():
    return re.findall(r"^\s+image:\s*(\S+)", COMPOSE.read_text(), re.M)

def test_every_image_is_pinned_to_something_that_cannot_move():
    floating = [
        image for image in images()
        if "@sha256:" not in image and not re.search(r":\d", image)
    ]

    assert not floating, (
        f"these tags can move under the range without anyone touching the repo, "
        f"so the same commit scores differently on different days: {floating}"
    )

def test_the_sensor_and_the_target_are_pinned_by_digest():
    sensor = [i for i in images() if "suricata" in i]
    target = [i for i in images() if "juice-shop" in i]

    assert sensor and all("@sha256:" in i for i in sensor), sensor
    assert target and all("@sha256:" in i for i in target), target

def host_ip(entry):
    if isinstance(entry, dict):
        return entry.get("host_ip")
    address = str(entry).split("/")[0]
    if address.startswith("["):
        return address[1:address.index("]")]
    return ":".join(address.split(":")[:-2]) or None

def published(text):
    for name, service in (yaml.safe_load(text).get("services") or {}).items():
        if service.get("network_mode") == "host":
            yield name, "network_mode: host", None
        for entry in service.get("ports") or []:
            yield name, entry, host_ip(entry)

def unpinned(text):
    return [(service, entry) for service, entry, host in published(text) if host != "127.0.0.1"]

def test_every_published_port_answers_on_loopback_only():
    text = COMPOSE.read_text()

    assert list(published(text)) and not unpinned(text), (
        f"{unpinned(text)} are not bound to 127.0.0.1, so each segment's "
        f"gateway forwards them back into the range and colima's forwarder "
        f"offers them to the whole LAN"
    )

def test_the_loopback_guard_reads_a_port_however_compose_lets_it_be_written():
    text = """
services:
  quoted:
    ports: ["127.0.0.1:8001:8001", "8002:8002"]
  bare:
    ports:
      - 127.0.0.1:8003:8003
      - 5601:5601
      - 22:22
      - 3000
  long:
    ports:
      - target: 9000
        published: 9000
      - {target: 9001, published: 9001, host_ip: 127.0.0.1}
      - {target: 9002, published: "9002", host_ip: 0.0.0.0}
  other:
    ports:
      - "127.0.0.1:7000-7001:7000-7001/udp"
      - "[::]:7002:7002"
      - "::1:7003:7003"
      - "0.0.0.0:7004:7004/tcp"
  hostnet:
    network_mode: host
"""

    caught = sorted(service for service, _ in unpinned(text))

    assert caught == sorted(
        ["quoted"] + ["bare"] * 3 + ["long"] * 2 + ["other"] * 3 + ["hostnet"]
    ), (
        f"the guard flagged {caught}. Compose publishes on every address a "
        f"port written unquoted, a bare container port, a long-syntax entry "
        f"with no host_ip and everything on network_mode host, so a guard "
        f"that reads only the double-quoted short form passes each of them"
    )

def test_the_platform_s_store_outlives_the_checkout_that_started_it():
    compose = yaml.safe_load(COMPOSE.read_text())
    platform = compose["services"]["platform"]
    store = platform["environment"]["DJANGO_DB_PATH"].rsplit("/", 1)[0]
    mounted = {
        entry.split(":")[1]: entry.split(":")[0]
        for entry in platform["volumes"]
        if isinstance(entry, str) and entry.count(":") >= 1
    }

    assert mounted.get(store) in (compose.get("volumes") or {}), (
        f"{store} is mounted from {mounted.get(store)!r}, a directory inside "
        f"whichever checkout ran compose up. The sessions, cases and scores are "
        f"the only store there is, and removing that checkout removes them"
    )

def test_the_waf_s_health_check_never_reaches_the_sensor():
    check = yaml.safe_load(COMPOSE.read_text())["services"]["waf"]["healthcheck"]["test"]
    asked = re.search(r"https?://[^/\s\"]+(/[^\s\"]*)?", " ".join(check))

    assert asked and asked.group(1) == "/healthz", (
        f"the WAF's health check asks {asked and asked.group(1)!r}. The image's "
        f"nginx answers /healthz itself and proxies every other path to "
        f"juice-shop over the estate leg, where Suricata writes an http event "
        f"for it: 360 an hour for as long as the stack runs. Ingest reads at "
        f"most 5000 documents of a session's window, oldest first, so a "
        f"session open 14 hours reads health checks and never the alerts after "
        f"them"
    )

def test_the_sensor_restarts_with_the_waf_whose_network_it_watches():
    suricata = yaml.safe_load(COMPOSE.read_text())["services"]["suricata"]
    declared = (suricata.get("depends_on") or {}).get("waf")

    assert suricata["network_mode"] == "service:waf"
    assert declared is None or declared.get("restart") is True, (
        f"suricata declares depends_on waf as {declared}. network_mode "
        f"service:waf already gives it that dependency with restart: true, and "
        f"a declaration without restart replaces it: compose then restarts the "
        f"waf and leaves suricata, which captures inside the waf's network "
        f"namespace, as it was"
    )

def test_the_red_box_s_recon_line_scans_the_port_the_target_listens_on():
    listening = yaml.safe_load(COMPOSE.read_text())["services"]["waf"]["environment"]["PORT"]
    motd = (COMPOSE.parent / "deploy/kali/motd").read_text()
    scanned = re.search(r"nmap .*-p (\S+) \$FSL_TARGET_HOST", motd)

    assert scanned and listening in scanned[1].split(","), (
        f"the red box's cheat sheet scans port {scanned and scanned[1]!r} of "
        f"shop.com and the waf behind that name listens on {listening}. The "
        f"box is on the edge network, not the host, so a port only the host "
        f"publishes reads as closed"
    )
