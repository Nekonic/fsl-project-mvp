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


def test_the_disk_is_converted_to_qcow2_and_put_to_glance_with_the_handed_token():
    assert "qemu-img convert -f raw -O qcow2" in BUILD
    assert images.UPLOAD in BUILD
    assert 'X-Auth-Token: $TOKEN' in BUILD and "-X PUT" in BUILD
    assert line("qemu-img convert") < line("-X PUT")


def test_the_upload_url_and_token_reach_the_builder_outside_the_bundle():
    bundle = edge_bundle()
    upload = {"url": "http://glance:9292/v2/images/img-9/file", "token": "tok-1"}

    config = yaml.safe_load(base64.b64decode(images.user_data(bundle, upload)).decode())

    [written] = [entry for entry in config["write_files"] if entry["path"] == images.UPLOAD]
    assert written["permissions"] == "0600"
    assert written["content"] == "http://glance:9292/v2/images/img-9/file\ntok-1\n"
    assert "tok-1" not in members(bundle).values()


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


class Glance:
    def __init__(self):
        self.images = [{"id": "img-ubuntu", "name": "ubuntu-24.04", "status": "active"}]
        self.servers = []
        self.consoles = {}
        self.calls = []
        self.ids = itertools.count(1)

    def token(self):
        return "tok-fresh"

    def __call__(self, call, body=None):
        verb, url = call.split(" ", 1)
        parts = urlsplit(url)
        path, query = parts.path.strip("/"), parse_qs(parts.query)
        self.calls.append((verb, path, body))
        if verb == "GET" and path == "v2/images":
            return {"images": [i for i in self.images if i["name"] == query["name"][0]]}
        if verb == "POST" and path == "v2/images":
            made = dict(body, id=f"img-{next(self.ids)}", status="queued")
            self.images.append(made)
            return made
        if verb == "GET" and path == "v2.1/flavors":
            return {"flavors": [{"id": "f-2", "name": "m1.medium"}]}
        if verb == "GET" and path == "v2.1/servers/detail":
            return {"servers": self.servers}
        if verb == "POST" and path == "v2.1/servers":
            made = dict(body["server"], id=f"srv-{next(self.ids)}", status="ACTIVE",
                        created="2026-10-11T12:00:00Z", addresses={})
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
                            network="net-platform", mtu=1450, opnsense=RELEASE)
    made = openstack.OpenStack(edge_only(), SPEC, get=glance, build=build)
    made._public_key = lambda make=False: KEY
    return made


def test_a_missing_edge_image_gets_a_glance_record_and_a_builder_that_fills_it():
    glance = Glance()

    plan = adapter(glance).ensure_images()

    [record] = [i for i in glance.images if i["name"] == "fsl-opnsense-26.7"]
    assert (record["disk_format"], record["container_format"]) == ("qcow2", "bare")
    assert record["hw_vif_model"] == "virtio" and record["min_ram"] == 3072
    [server] = glance.servers
    assert server["imageRef"] == "img-ubuntu" and server["flavorRef"] == "f-2"
    config = yaml.safe_load(base64.b64decode(server["user_data"]).decode())
    [upload] = [e for e in config["write_files"] if e["path"] == images.UPLOAD]
    assert upload["content"] == f"http://glance:9292/v2/images/{record['id']}/file\ntok-fresh\n"
    assert [found.state for found in plan.images] == ["building"]


def test_a_finished_upload_is_ready_and_its_builder_goes_without_a_snapshot():
    glance = Glance()
    adapter(glance).ensure_images()
    [record] = [i for i in glance.images if i["name"] == "fsl-opnsense-26.7"]
    record["status"] = "active"
    glance.consoles[glance.servers[0]["id"]] = f"{images.READY} {record[images.BUNDLE]}\n"

    plan = adapter(glance).ensure_images()

    assert not glance.servers and plan.clean
    assert not [c for c in glance.calls if c[2] and ("createImage" in c[2] or "os-stop" in c[2])], (
        "a snapshot of the builder would be Ubuntu, not the disk it uploaded"
    )


def test_a_builder_that_failed_is_reported_with_its_console_and_cleaned_up():
    glance = Glance()
    adapter(glance).ensure_images()
    [record] = [i for i in glance.images if i["name"] == "fsl-opnsense-26.7"]
    glance.consoles[glance.servers[0]["id"]] = (
        f"sha256sum: WARNING: 1 computed checksum did NOT match\n{images.FAILED} {record[images.BUNDLE]}\n")

    [found] = adapter(glance).plan_images().images
    assert found.state == "failed" and "did NOT match" in found.detail

    adapter(glance).clean_images()
    adapter(glance).clean_images()
    assert not glance.servers and not [i for i in glance.images if i["name"] == "fsl-opnsense-26.7"]


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
