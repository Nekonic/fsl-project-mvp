import pathlib
import re

import yaml

from tests import composed
from wargames import WARGAMES

COMPOSE = composed.COMPOSE

def images():
    return re.findall(r"^\s+image:\s*(\S+)", composed.text(), re.M)

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

def test_every_service_runs_on_x86_64():
    elsewhere = {
        name: service.get("platform")
        for name, service in composed.services().items()
        if service.get("platform") != "linux/amd64"
    }

    assert not elsewhere, (
        f"production is OpenStack on x86_64; these services would run on "
        f"whatever architecture the Docker host has: {elsewhere}"
    )

def networks_of(service):
    joined = service.get("networks") or []
    return sorted(joined if isinstance(joined, list) else joined)

def test_the_board_and_its_database_stand_inside_the_estate_only():
    services = composed.services()

    for name in ("board", "board-db"):
        assert networks_of(services[name]) == ["estate"], (name, networks_of(services[name]))
        assert not services[name].get("ports"), f"{name} is published past the WAF"

def test_the_board_is_reached_by_name_through_the_waf():
    waf = composed.services()["waf"]
    outside = [n for n in waf["networks"] if n.startswith("edge")]

    missing = [n for n in outside if "board.com" not in (waf["networks"][n] or {}).get("aliases", [])]
    assert not missing, f"an attacker on {missing} cannot resolve board.com"

def test_the_database_is_pinned_by_digest():
    database = [i for i in images() if i.startswith("mysql")]

    assert database and all("@sha256:" in i for i in database), database

def test_the_platform_needs_no_build_argument_to_come_up():
    platform = composed.services()["platform"]
    build = platform.get("build")
    args = build.get("args") if isinstance(build, dict) else None

    assert not args, (
        f"a fresh host runs `docker compose up` with nothing else; a required "
        f"build arg breaks that. The platform sorts the docker socket group out "
        f"at start instead: {args}"
    )

def test_the_platform_registers_the_ingest_pipeline_itself():
    platform = composed.services()["platform"]
    mounted = [v for v in platform["volumes"] if "deploy/elastic" in v]

    assert mounted, (
        "bring-up would still need a manual pipeline PUT; mount deploy/elastic "
        "so the platform can register fsl-geoip on start"
    )

def test_no_image_downloads_a_binary_built_for_another_architecture():
    root = COMPOSE.parent
    dockerfiles = [
        *(root / "deploy").glob("*/Dockerfile"),
        *(root / "wargames").glob("*/*/Dockerfile"),
        root / "platform" / "Dockerfile",
    ]
    foreign = [
        str(path.relative_to(root))
        for path in dockerfiles
        if re.search(r"aarch64|arm64", path.read_text())
    ]

    assert not foreign, f"these fetch an ARM binary into an x86_64 image: {foreign}"

def host_ip(entry):
    if isinstance(entry, dict):
        return entry.get("host_ip")
    address = re.sub(r"\$\{[A-Z_]+:-([^}]*)\}", r"\1", str(entry).split("/")[0])
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
    texts = [path.read_text() for path in composed.files()]
    loose = [entry for text in texts for entry in unpinned(text)]

    assert any(list(published(text)) for text in texts) and not loose, (
        f"{loose} are not bound to 127.0.0.1, so each segment's "
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
    compose = composed.document()
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
    check = composed.services()["waf"]["healthcheck"]["test"]
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
    suricata = composed.services()["suricata"]
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
    listening = composed.services()["waf"]["environment"]["PORT"]
    motd = (COMPOSE.parent / "deploy/kali/motd").read_text()
    scanned = re.search(r"nmap .*-p (\S+) \$FSL_TARGET_HOST", motd)

    assert scanned and listening in scanned[1].split(","), (
        f"the red box's cheat sheet scans port {scanned and scanned[1]!r} of "
        f"shop.com and the waf behind that name listens on {listening}. The "
        f"box is on the edge network, not the host, so a port only the host "
        f"publishes reads as closed"
    )

def test_the_waf_writes_its_audit_log_where_its_own_user_can():
    services = composed.services()
    audit_dir = services["waf"]["environment"]["MODSEC_AUDIT_LOG"].rsplit("/", 1)[0]
    [source] = [
        volume.split(":")[0] for volume in services["waf"]["volumes"]
        if volume.split(":")[1] == audit_dir
    ]

    assert audit_dir == "/var/log/modsecurity/audit" and not source.startswith("."), (
        f"{source} on {audit_dir}: the WAF runs as nginx, a bind mount's "
        f"directory is created by dockerd as root, and only the image's "
        f"audit directory belongs to nginx, which a named volume copies. On a "
        f"Linux Docker host the audit log never appeared"
    )
    assert any(volume.startswith(f"{source}:") and volume.endswith(":ro")
               for volume in services["filebeat"]["volumes"]), (
        "Filebeat does not read the volume the WAF writes"
    )

def test_every_wargame_is_one_folder_the_stack_includes():
    included = {
        str(path.relative_to(composed.ROOT)) for path in composed.files()[1:]
    }
    folders = {
        str(path.relative_to(composed.ROOT))
        for path in (composed.ROOT / "wargames").glob("*/compose.yaml")
    }

    assert folders and included == folders, (
        f"compose.yaml includes {sorted(included)} and the wargames folder holds "
        f"{sorted(folders)}: a wargame is added or removed as one folder"
    )
    assert {path.split("/")[1] for path in folders} == set(WARGAMES), (
        "the console offers a wargame with no folder, or a folder with no wargame"
    )

def test_only_the_platform_and_the_log_collector_may_be_published_elsewhere_and_only_by_choice():
    chosen = {
        name: entry
        for name, service in composed.services().items()
        for entry in service.get("ports") or []
        if "${" in str(entry)
    }

    assert chosen == {
        "platform": "${FSL_PUBLISH:-127.0.0.1}:8000:8000",
        "filebeat": "${FSL_SYSLOG_PUBLISH:-127.0.0.1}:5140:5140/udp",
    }, chosen

def test_the_address_a_vm_publishes_on_stays_out_of_git():
    import subprocess

    ignored = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=COMPOSE.parent)

    assert ignored.returncode == 0
