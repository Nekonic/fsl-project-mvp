import base64
import importlib.util
import io
import itertools
import pathlib
import socket
import tarfile
import threading
import time
import xml.etree.ElementTree as ElementTree
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from range import cloud, declared, images, openstack, opnsense

ROOT = pathlib.Path(__file__).resolve().parents[2]
OS = declared.read(flavor="openstack")
EDGE = OS.hosts["fsl-edge"]
RELEASE = cloud.read(cloud.EXAMPLE).opnsense
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPlatformKey fsl-platform"
BUILD = (ROOT / "deploy/opnsense/build.sh").read_text()
SPEC = openstack.Cloud(
    keystone="http://keystone:5000", neutron="http://neutron:9696",
    nova="http://nova:8774/v2.1", glance="http://glance:9292", project="fsl",
    user="fsl", ssh_user="ubuntu", ssh_key="/keys/fsl",
)


def edge_bundle(release=RELEASE, mtu=1450, key=KEY):
    generated = opnsense.image_bundle((ROOT / opnsense.CONFIG).read_text(), release, mtu, key)
    return images.bundle(ROOT, "fsl-edge", EDGE.setup, EDGE.files, generated=generated,
                         image=release.image, uploads=True)


def members(bundle):
    with tarfile.open(fileobj=io.BytesIO(bundle.archive)) as archive:
        return {m.name: archive.extractfile(m).read() for m in archive.getmembers()}


def line(text):
    return next(i for i, entry in enumerate(BUILD.splitlines()) if text in entry)


def test_the_edge_is_built_by_a_script_and_uploads_its_own_disk():
    assert EDGE.setup == "deploy/opnsense/build.sh" and not EDGE.image
    assert EDGE.uploads == opnsense.UPLOADS


def test_the_image_is_named_by_release_and_rebuilt_when_the_release_changes():
    from dataclasses import replace

    first, second = edge_bundle(), edge_bundle(replace(RELEASE, version="27.1"))

    assert first.name == "fsl-opnsense-26.7" and second.name == "fsl-opnsense-27.1"
    assert first.digest != second.digest
    assert edge_bundle().digest == first.digest
    assert edge_bundle(mtu=1500).digest != first.digest, "the MTU is baked into the image"


def test_the_bundle_carries_the_release_settings_and_the_image_config():
    found = members(edge_bundle())
    settings = found[opnsense.IMAGE_SETTINGS].decode()
    config = ElementTree.fromstring(found[opnsense.IMAGE_CONFIG])

    assert f"VERSION=26.7" in settings and f"IMAGE_SHA256={RELEASE.image_sha256}" in settings
    assert f"PUBKEY_SHA256={RELEASE.pubkey_sha256}" in settings
    assert f"NANO={RELEASE.nano}" in settings
    assert config.findtext("interfaces/opt1/ipaddr") == "dhcp"
    assert config.findtext("interfaces/opt1/mtu") == "1450"
    assert "deploy/opnsense/importer.py" in found and "deploy/opnsense/build.sh" in found


def test_the_image_keeps_the_serial_console_and_its_login_prompt_after_the_import():
    config = ElementTree.fromstring(members(edge_bundle())[opnsense.IMAGE_CONFIG])

    assert config.findtext("system/primaryconsole") == "serial", (
        "the nano image's own config puts the console on serial; without it the import moves "
        "the console to video and the builder never sees login:"
    )
    assert config.findtext("system/serialspeed") == "115200"
    assert config.find("system/disableconsolemenu") is not None, (
        "without it the serial console logs root in to the console menu with no password"
    )


def test_a_generated_file_may_not_shadow_one_from_the_repo():
    with pytest.raises(Exception, match="both a repo file and a generated one"):
        images.bundle(ROOT, "fsl-edge", EDGE.setup, EDGE.files,
                      generated={"deploy/opnsense/config.xml": b"x"})


def test_the_builder_installs_every_tool_it_uses_on_the_stock_ubuntu_image():
    installed = BUILD[BUILD.index("$APT install"):BUILD.index("rm -rf")].split()

    for package in ("curl", "bzip2", "openssl", "qemu-utils", "qemu-system-x86",
                    "dosfstools", "mtools", "fdisk", "python3", "ca-certificates"):
        assert package in installed, package
    assert line("$APT install") < line("curl -fsSLo")


def test_the_download_is_checked_before_anything_is_unpacked_or_booted():
    assert line('sha256sum -c -') < line("bunzip2")
    assert line("PUBKEY_SHA256") < line("openssl dgst -sha256 -verify")
    assert line("openssl dgst -sha256 -verify") < line("importer.py")
    assert "set -eu" in BUILD.splitlines()[0], "a failed check must stop the build"


def test_the_signature_is_checked_on_the_unpacked_image_as_the_release_notes_say():
    assert line("bunzip2") < line("openssl base64 -d")
    assert '-signature image.sig "$NANO"' in BUILD


def test_the_disk_is_converted_to_qcow2_where_the_builder_serves_it():
    assert f'qemu-img convert -f raw -O qcow2 -c "$NANO" {images.SERVED}/{images.DISK}' in BUILD
    assert "TOKEN" not in BUILD and "X-Auth-Token" not in BUILD and "-X PUT" not in BUILD
    assert line("openssl dgst -sha256 -verify") < line("qemu-img convert")


def test_the_builder_gets_no_credential_and_serves_its_disk_with_its_sha256():
    bundle = edge_bundle()

    config = yaml.safe_load(base64.b64decode(images.user_data(bundle)).decode())

    assert [entry["path"] for entry in config["write_files"]] == [f"{images.WORKDIR}/image.tar.gz"]
    [[_, _, script]] = config["runcmd"]
    assert f"sha256sum {images.SERVED}/{images.DISK}" in script
    assert f"systemd-run --unit=fsl-serve /usr/bin/python3 -m http.server {images.SERVE_PORT}" in script
    assert f"{images.READY} {bundle.digest} sha256=$sha" in script
    assert script.index("http.server") < script.index(images.READY), (
        "the ready line is the platform's cue to pull, so the server must already run")


def importer():
    path = ROOT / "deploy/opnsense/importer.py"
    spec = importlib.util.spec_from_file_location("fsl_importer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_importer_answers_each_prompt_of_the_opnsense_console_in_turn():
    module = importer()
    ours, theirs = socket.socketpair()
    ours.settimeout(1)
    printed = (b"Press any key to start the configuration importer: ...",
               b"Select device to import from (e.g. ada0) or leave blank to exit: ",
               b"Restoring config.xml...done.\n", b"\nfsl-edge login: ")
    answers = []

    def console():
        for said in printed:
            theirs.sendall(said)
            theirs.settimeout(0.2)
            try:
                answers.append(theirs.recv(64))
            except socket.timeout:
                answers.append(b"")

    threading.Thread(target=console, daemon=True).start()
    heard = bytearray()
    for wanted, answer in module.STEPS:
        module.awaited(ours, wanted, float("inf"), heard)
        if answer:
            ours.sendall(answer)

    assert answers[:2] == [b"x", b"vtbd1\r"], (
        "the seed disk is the second virtio disk, which FreeBSD names vtbd1"
    )


def test_the_importer_gives_up_with_what_the_console_said():
    module = importer()
    ours, theirs = socket.socketpair()
    ours.settimeout(0.1)
    theirs.sendall(b"Mounting filesystems...\n")

    with pytest.raises(SystemExit, match="Mounting filesystems"):
        module.awaited(ours, b"login:", time.monotonic() + 0.5, bytearray())


def test_the_importer_presses_the_power_button_until_qemu_exits():
    module = importer()
    module.PRESS_EVERY = 0.2
    console, _ = socket.socketpair()
    monitor, pressed = socket.socketpair()

    class Qemu:
        polls = itertools.chain([None] * 6, itertools.repeat(0))

        def poll(self):
            return next(self.polls)

    module.powered_off(Qemu(), console, monitor)
    pressed.settimeout(0.5)

    assert pressed.recv(4096).count(b"system_powerdown\n") >= 2, (
        "OPNsense ignores a power button pressed as login: appears, so it is pressed again"
    )


class Glance:
    def __init__(self):
        self.images = [{"id": "img-ubuntu", "name": "ubuntu-24.04", "status": "active"}]
        self.servers = []
        self.consoles = {}
        self.calls = []
        self.uploaded = []
        self.groups = []
        self.ports = [{"id": "port-platform", "network_id": "net-platform", "device_id": "vm-platform",
                       "fixed_ips": [{"ip_address": "10.20.0.5"}]}]
        self.ids = itertools.count(1)

    def upload(self, url, disk):
        self.uploaded.append((url, disk.read_bytes()))

    def __call__(self, call, body=None):
        verb, url = call.split(" ", 1)
        parts = urlsplit(url)
        path, query = parts.path.strip("/"), parse_qs(parts.query)
        self.calls.append((verb, path, body))
        if verb == "GET" and path == "v2/images" and "name" in query:
            return {"images": [i for i in self.images if i["name"] == query["name"][0]]}
        if verb == "GET" and path == "v2/images":
            return {"images": self.images}
        if verb == "POST" and path == "v2/images":
            made = dict(body, id=f"img-{next(self.ids)}", status="queued")
            self.images.append(made)
            return made
        if verb == "GET" and path == "v2.1/flavors":
            return {"flavors": [{"id": "f-2", "name": "m1.medium"}]}
        if verb == "GET" and path == "v2.0/ports":
            return {"ports": [p for p in self.ports if p["network_id"] == query["network_id"][0]]}
        if verb == "GET" and path == "v2.0/security-groups":
            return {"security_groups": self.groups}
        if verb == "POST" and path == "v2.0/security-groups":
            made = {"id": f"sg-{next(self.ids)}", "name": body["security_group"]["name"],
                    "security_group_rules": [{"id": "egress-4", "direction": "egress", "ethertype": "IPv4"}]}
            self.groups.append(made)
            return {"security_group": made}
        if verb == "POST" and path == "v2.0/security-group-rules":
            rule = dict(body["security_group_rule"], id=f"rule-{next(self.ids)}")
            next(g for g in self.groups if g["id"] == rule["security_group_id"])["security_group_rules"].append(rule)
            return {"security_group_rule": rule}
        if verb == "DELETE" and path.startswith("v2.0/security-group-rules/"):
            ident = path.rsplit("/", 1)[1]
            for group in self.groups:
                group["security_group_rules"] = [r for r in group["security_group_rules"] if r["id"] != ident]
            return {}
        if verb == "GET" and path == "v2.1/servers/detail":
            return {"servers": self.servers}
        if verb == "POST" and path == "v2.1/servers":
            made = dict(body["server"], id=f"srv-{next(self.ids)}", status="ACTIVE",
                        created="2026-10-11T12:00:00Z", addresses={"fsl-platform": [
                            {"addr": "127.0.0.1", "version": 4, "OS-EXT-IPS:type": "fixed"}]})
            self.servers.append(made)
            return {"server": {"id": made["id"]}}
        if verb == "POST" and path.endswith("/action") and "os-getConsoleOutput" in body:
            return {"output": self.consoles.get(path.split("/")[2], "")}
        if verb == "DELETE" and path.startswith("v2.1/servers/"):
            self.servers = [s for s in self.servers if s["id"] != path.rsplit("/", 1)[1]]
            return {}
        if verb == "DELETE" and path.startswith("v2/images/"):
            self.images = [i for i in self.images if i["id"] != path.rsplit("/", 1)[1]]
            return {}
        raise AssertionError(call)


def edge_only():
    from range.declared import Declaration

    return Declaration(roles={"edge": "fsl-edge"}, hosts={"fsl-edge": EDGE})


def adapter(glance):
    build = openstack.Build(source=str(ROOT), base_image="ubuntu-24.04", build_flavor="m1.medium",
                            network="net-platform", mtu=1450, opnsense=RELEASE, platform="vm-platform")
    made = openstack.OpenStack(edge_only(), SPEC, get=glance, build=build)
    made._public_key = lambda make=False: KEY
    return made


@pytest.fixture
def served(tmp_path, monkeypatch):
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    disk = tmp_path / images.DISK
    disk.write_bytes(b"QFI\xfb" + bytes(range(256)) * 64)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(images, "SERVE_PORT", server.server_port)
    yield disk
    server.shutdown()


def finished(glance, disk, sha=None):
    import hashlib

    [builder] = glance.servers
    digest = builder["metadata"][images.BUNDLE]
    glance.consoles[builder["id"]] = (
        f"{images.READY} {digest} sha256={sha or hashlib.sha256(disk.read_bytes()).hexdigest()}\n")


def test_a_missing_edge_image_gets_a_builder_and_no_glance_record_yet():
    glance = Glance()

    plan = adapter(glance).ensure_images()

    assert not [i for i in glance.images if i["name"] == "fsl-opnsense-26.7"]
    [server] = glance.servers
    assert server["imageRef"] == "img-ubuntu" and server["flavorRef"] == "f-2"
    assert server["security_groups"] == [{"name": "fsl-build"}], (
        "the platform pulls the disk from the builder, which the default group would refuse")
    assert "token" not in base64.b64decode(server["user_data"]).decode().lower()
    assert [found.state for found in plan.images] == ["building"]


def test_the_builder_s_group_lets_in_only_the_platform_on_the_disk_port():
    glance = Glance()

    adapter(glance).ensure_images()

    [group] = glance.groups
    ingress = [r for r in group["security_group_rules"] if r["direction"] == "ingress"]
    assert [(r["protocol"], r["port_range_min"], r["port_range_max"], r["remote_ip_prefix"])
            for r in ingress] == [("tcp", images.SERVE_PORT, images.SERVE_PORT, "10.20.0.5/32")]
    assert [r for r in group["security_group_rules"] if r["direction"] == "egress"], (
        "the builder downloads packages and the release, so egress stays")


def test_the_builder_s_group_is_made_once_and_follows_a_replaced_platform():
    glance = Glance()
    adapter(glance).ensure_images()
    glance.servers.clear()
    glance.ports[0]["fixed_ips"] = [{"ip_address": "10.20.0.9"}]

    adapter(glance).ensure_images()

    [group] = glance.groups
    assert [r["remote_ip_prefix"] for r in group["security_group_rules"]
            if r["direction"] == "ingress"] == ["10.20.0.9/32"]


def test_a_served_disk_is_pulled_checked_and_put_to_glance_by_the_platform(served):
    glance = Glance()
    adapter(glance).ensure_images()
    finished(glance, served)

    adapter(glance).ensure_images()

    [record] = [i for i in glance.images if i["name"] == "fsl-opnsense-26.7"]
    assert (record["disk_format"], record["container_format"]) == ("qcow2", "bare")
    assert record["hw_vif_model"] == "virtio" and record["min_ram"] == 3072
    assert glance.uploaded == [(f"http://glance:9292/v2/images/{record['id']}/file", served.read_bytes())]


def test_a_disk_whose_sha256_differs_from_the_builder_s_word_never_reaches_glance(served):
    from range.ports import RangeUnavailable

    glance = Glance()
    adapter(glance).ensure_images()
    finished(glance, served, sha="0" * 64)

    with pytest.raises(RangeUnavailable, match="nothing went to Glance"):
        adapter(glance).ensure_images()
    assert not glance.uploaded and not [i for i in glance.images if i["name"] == "fsl-opnsense-26.7"]


def test_a_record_left_queued_by_an_interrupted_upload_is_filled_not_duplicated(served):
    glance = Glance()
    adapter(glance).ensure_images()
    finished(glance, served)
    glance.images.append(dict(images.record(edge_bundle(), opnsense.IMAGE_PROPERTIES),
                              id="img-left", status="queued"))

    [found] = adapter(glance).plan_images().images
    assert (found.state, found.image) == ("built", "img-left")
    adapter(glance).ensure_images()
    assert [url for url, _ in glance.uploaded] == ["http://glance:9292/v2/images/img-left/file"]


def test_a_finished_upload_is_ready_and_its_builder_goes_without_a_snapshot(served):
    glance = Glance()
    adapter(glance).ensure_images()
    finished(glance, served)
    adapter(glance).ensure_images()
    [record] = [i for i in glance.images if i["name"] == "fsl-opnsense-26.7"]
    record["status"] = "active"

    plan = adapter(glance).ensure_images()

    assert not glance.servers and plan.clean
    assert not [c for c in glance.calls if c[2] and ("createImage" in c[2] or "os-stop" in c[2])], (
        "a snapshot of the builder would be Ubuntu, not the disk it made"
    )


def test_a_builder_that_failed_is_reported_with_its_console_and_cleaned_up():
    glance = Glance()
    adapter(glance).ensure_images()
    [builder] = glance.servers
    glance.consoles[builder["id"]] = (
        f"sha256sum: WARNING: 1 computed checksum did NOT match\n"
        f"{images.FAILED} {builder['metadata'][images.BUNDLE]}\n")

    [found] = adapter(glance).plan_images().images
    assert found.state == "failed" and "did NOT match" in found.detail

    adapter(glance).clean_images()
    adapter(glance).clean_images()
    assert not glance.servers and not [i for i in glance.images if i["name"] == "fsl-opnsense-26.7"]


def test_an_edge_image_of_a_release_no_longer_configured_is_cleaned_but_never_a_foreign_one():
    glance = Glance()
    glance.images += [
        {"id": "img-old", "name": "fsl-opnsense-26.1", "status": "active", images.BUNDLE: "0" * 16},
        {"id": "img-theirs", "name": "fsl-opnsense-hand-made", "status": "active"},
    ]

    plan = adapter(glance).plan_images()

    assert [(kind, ident) for kind, ident, _ in plan.leftovers] == [("image", "img-old")]
    adapter(glance).clean_images()
    assert {i["id"] for i in glance.images} == {"img-ubuntu", "img-theirs"}


def test_an_old_edge_image_a_server_still_boots_from_is_kept_until_it_is_rebuilt():
    glance = Glance()
    glance.images.append(
        {"id": "img-old", "name": "fsl-opnsense-26.1", "status": "active", images.BUNDLE: "0" * 16})
    glance.servers.append({"id": "srv-edge", "name": "fsl-edge", "status": "ACTIVE",
                           "image": {"id": "img-old"}, "metadata": {}})

    assert not adapter(glance).plan_images().leftovers
    adapter(glance).clean_images()
    assert "img-old" in {i["id"] for i in glance.images}

    glance.servers[0]["image"] = {"id": "img-new"}
    assert [ident for _, ident, _ in adapter(glance).plan_images().leftovers] == ["img-old"]


def test_the_edge_image_needs_the_fabric_key_and_the_release_settings():
    from range.ports import RangeUnavailable

    glance = Glance()
    keyless = adapter(glance)
    keyless._public_key = lambda make=False: ""
    with pytest.raises(RangeUnavailable, match="build the fabric first"):
        keyless.plan_images()

    bare = openstack.OpenStack(edge_only(), SPEC, get=glance,
                               build=openstack.Build(source=str(ROOT), mtu=1450))
    with pytest.raises(RangeUnavailable, match="FSL_OPNSENSE"):
        bare.plan_images()


def test_a_host_that_uploads_an_image_needs_the_script_that_makes_it():
    from range.declared import Declaration, Host

    with pytest.raises(ValueError, match="no setup script to make it"):
        Declaration(roles={"edge": "fsl-x"},
                    hosts={"fsl-x": Host(image="img", uploads="opnsense")}).check()
