import re

import yaml

from tests import composed
from wargames import WARGAMES

COMPOSE = composed.COMPOSE


def pulled_images():
    return [
        service["image"] for service in composed.services().values()
        if "image" in service and "build" not in service
    ]

def test_every_image_is_pinned_to_something_that_cannot_move():
    floating = [
        image for image in pulled_images()
        if "@sha256:" not in image and not re.search(r":\d", image)
    ]

    assert not floating, (
        f"these tags can move under the range without anyone touching the repo, "
        f"so the same commit scores differently on different days: {floating}"
    )

def test_every_built_image_is_named_where_ci_publishes_it():
    unnamed = {
        name: service.get("image")
        for name, service in composed.services().items()
        if "build" in service
        and not re.fullmatch(r"ghcr\.io/nekonic/fsl-[a-z0-9-]+:\$\{FSL_IMAGE_TAG:-dev\}",
                             service.get("image") or "")
    }

    assert not unnamed, (
        f"these are built without a ghcr.io/nekonic/fsl-...:${{FSL_IMAGE_TAG:-dev}} "
        f"name, so a VM cannot pull them and compose names them after the "
        f"project, and a second session's stack would build them again: {unnamed}"
    )


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

def test_every_wargame_is_one_folder():
    folders = {path.parent.name for path in composed.included()}

    assert folders and folders == set(WARGAMES), (
        "the console offers a wargame with no folder, or a folder with no wargame"
    )

def test_only_the_platform_the_gns3_server_and_the_syslog_collector_may_be_published_elsewhere_and_only_by_choice():
    chosen = {
        (name, entry)
        for name, service in composed.services().items()
        for entry in service.get("ports") or []
        if "${" in str(entry)
    }

    assert chosen == {
        ("platform", "${FSL_PUBLISH:-127.0.0.1}:8000:8000"),
        ("platform", "${FSL_PUBLISH:-127.0.0.1}:8002:8002"),
        ("gns3", "${FSL_PUBLISH:-127.0.0.1}:3080:3080"),
        ("collector", "${FSL_SYSLOG_PUBLISH:-127.0.0.1}:5140:5140/udp"),
    }, chosen

def test_the_address_a_vm_publishes_on_stays_out_of_git():
    import subprocess

    ignored = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=COMPOSE.parent)

    assert ignored.returncode == 0

def test_the_openstack_waf_vm_blocks_as_the_container_does():
    shipped = (COMPOSE.parent / "deploy/waf/modsecurity.conf").read_text()

    assert "SecRuleEngine On" in shipped.splitlines(), (
        "the VM ran DetectionOnly, so the lesson's attacks went through on OpenStack"
    )
