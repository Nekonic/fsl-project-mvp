import base64
import io
import pathlib
import tarfile

import pytest
import yaml

from range import declared, images
from range.ports import RangeUnavailable

ROOT = pathlib.Path(__file__).resolve().parents[2]

@pytest.fixture
def source(tmp_path):
    (tmp_path / "waf").mkdir()
    (tmp_path / "waf" / "setup.sh").write_text("set -eu\n")
    (tmp_path / "waf" / "site.conf").write_text("server {}\n")
    (tmp_path / "waf" / "__pycache__").mkdir()
    (tmp_path / "waf" / "__pycache__" / "x.pyc").write_bytes(b"\0")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "read.log").write_text("someone read this\n")
    return tmp_path

def packed(source, files=("waf",)):
    return images.bundle(source, "fsl-waf", "waf/setup.sh", files)

def members(bundle):
    with tarfile.open(fileobj=io.BytesIO(bundle.archive)) as archive:
        return {m.name: m for m in archive.getmembers()}

def cloud_config(bundle):
    text = base64.b64decode(images.user_data(bundle)).decode()
    assert text.startswith("#cloud-config\n")
    return yaml.safe_load(text)

def test_a_bundle_holds_the_setup_and_the_declared_files_and_nothing_else(source):
    found = members(packed(source))

    assert sorted(found) == ["waf/setup.sh", "waf/site.conf"]

def test_the_same_files_give_the_same_digest_and_any_change_gives_another(source):
    first = packed(source).digest
    assert packed(source).digest == first

    (source / "waf" / "site.conf").write_text("server { listen 81; }\n")
    assert packed(source).digest != first

def test_a_checkout_s_umask_does_not_change_the_digest_and_only_the_executable_bit_does(source):
    script = source / "waf" / "setup.sh"
    conf = source / "waf" / "site.conf"
    script.chmod(0o755)
    conf.chmod(0o644)
    cloned = packed(source)
    script.chmod(0o775)
    conf.chmod(0o664)
    sideloaded = packed(source)

    assert sideloaded.digest == cloned.digest
    assert {name: m.mode for name, m in members(sideloaded).items()} == {
        "waf/setup.sh": 0o755, "waf/site.conf": 0o644}
    script.chmod(0o664)
    assert packed(source).digest != cloned.digest

def test_a_build_time_file_is_packed_for_the_builder_and_left_out_of_the_digest(source):
    plain = packed(source)
    first = images.bundle(source, "fsl-waf", "waf/setup.sh", ("waf",), unhashed={"waf/served-from": b"http://a/\n"})
    moved = images.bundle(source, "fsl-waf", "waf/setup.sh", ("waf",), unhashed={"waf/served-from": b"http://b/\n"})

    assert "waf/served-from" in members(first)
    assert first.digest == moved.digest == plain.digest, (
        "where the builder fetches its inputs from is not what the image holds")
    with pytest.raises(RangeUnavailable, match="waf/site.conf"):
        images.bundle(source, "fsl-waf", "waf/setup.sh", ("waf",), unhashed={"waf/site.conf": b""})

def test_a_file_the_declaration_names_and_the_repo_lacks_is_refused_by_name(source):
    with pytest.raises(RangeUnavailable, match="waf/gone.conf"):
        packed(source, files=("waf", "waf/gone.conf"))

def test_the_builder_unpacks_runs_the_setup_and_says_on_its_console_how_it_went(source):
    bundle = packed(source)
    config = cloud_config(bundle)

    written = config["write_files"][0]
    assert written["encoding"] == "b64"
    assert base64.b64decode(written["content"]) == bundle.archive
    script = config["runcmd"][0][-1]
    assert f"sh {images.WORKDIR}/image/waf/setup.sh" in script
    assert script.index("setup.sh") < script.index(f"{images.READY} {bundle.digest}")
    assert f"{images.FAILED} {bundle.digest}" in script
    assert "poweroff" not in script, (
        "Nova on this cloud answers 404 for the console of a guest that is "
        "off, so a builder that powered itself off could never say whether "
        "its setup worked; the platform stops it after reading the console"
    )

BUNDLE = images.Bundle(host="fsl-waf", setup="waf/setup.sh", digest="d1", archive=b"")

def image(status="active", bundle="d1", ident="img-1"):
    return {"id": ident, "name": "fsl-waf", "status": status, images.BUNDLE: bundle}

def builder(status="ACTIVE", bundle="d1", ident="srv-1", host="fsl-waf"):
    return {"id": ident, "name": images.BUILDER + host, "status": status,
            "created": "2026-10-01T12:00:00Z",
            "metadata": {images.BUILDS: host, images.BUNDLE: bundle}}

def state(images_=(), builders=(), consoles=None):
    plan = images.plan((BUNDLE,), list(images_), list(builders), consoles or {})
    return plan.images[0], plan

@pytest.mark.parametrize("images_, builders, consoles, expected", [
    ((), (), {}, "missing"),
    ((), (builder(),), {}, "building"),
    ((), (builder(),), {"srv-1": f"...\n{images.READY} d1\nubuntu login:\n"}, "built"),
    ((), ({**builder(), "OS-EXT-STS:task_state": "powering-off"},), {"srv-1": f"{images.READY} d1\n"}, "building"),
    ((), (builder(),), {"srv-1": f"{images.READY} d0\n"}, "building"),
    ((), (builder("SHUTOFF"),), {}, "stopped"),
    ((image("saving"),), (builder("SHUTOFF"),), {}, "saving"),
    ((image(),), (builder("SHUTOFF"),), {}, "ready"),
], ids=["nothing", "running", "said-ready", "being-stopped", "other-bundle-ready", "stopped", "saving", "active"])
def test_a_bundle_s_image_moves_through_the_build_states(images_, builders, consoles, expected):
    found, _ = state(images_=images_, builders=builders, consoles=consoles)

    assert found.state == expected

@pytest.mark.parametrize("builders, consoles, said", [
    ((builder(),), {"srv-1": f"E: Unable to locate package nginx\n{images.FAILED} d1\n"}, "Unable to locate package nginx"),
    (({**builder(status="ERROR"), "fault": {"message": "No valid host was found"}},), {}, "No valid host was found"),
    ((builder(status="ERROR"),), {}, "ERROR"),
])
def test_a_builder_whose_setup_failed_says_why(builders, consoles, said):
    found, _ = state(builders=builders, consoles=consoles)

    assert found.state == "failed"
    assert said in found.detail

def test_an_active_image_of_this_bundle_is_ready_and_the_builder_left_is_not_clean():
    found, plan = state(images_=[image()], builders=[builder("SHUTOFF")])
    _, cleaned = state(images_=[image()])

    assert found.image == "img-1" and found.builder == "srv-1" and not plan.clean
    assert cleaned.clean

@pytest.mark.parametrize("images_, builders, left", [
    ([image(bundle="d0", ident="img-old")], [], ("image", "img-old")),
    ([], [builder(bundle="d0", ident="srv-old")], ("server", "srv-old")),
])
def test_an_image_or_builder_of_another_bundle_is_left_over_and_does_not_stand_in(images_, builders, left):
    found, plan = state(images_=images_, builders=builders)

    assert found.state == "missing"
    assert [(kind, ident) for kind, ident, _ in plan.leftovers] == [left]

def test_what_cleaning_removes_is_leftovers_and_failures_never_a_ready_image():
    plan = images.plan(
        (BUNDLE, images.Bundle("fsl-wiki", "wiki/setup.sh", "w1", b"")),
        [image(), image(bundle="d0", ident="img-old")],
        [builder(bundle="w1", ident="srv-wiki", host="fsl-wiki")],
        {"srv-wiki": f"Traceback\n{images.FAILED} w1\n"},
    )

    assert images.removable(plan) == [("image", "img-old"), ("server", "srv-wiki")]

def test_a_prebuilt_image_the_cloud_already_holds_is_ready_with_no_builder():
    glance = [{"id": "img-edge", "name": "fsl-edge", "status": "active"}]

    plan = images.plan((), glance, [], {}, prebuilt=[("fsl-edge", "fsl-edge")])
    [found] = plan.images
    lacking = images.plan((), [], [], {}, prebuilt=[("fsl-edge", "fsl-edge")])

    assert found.host == "fsl-edge"
    assert found.state == "ready" and found.image == "img-edge" and not found.builder
    assert plan.clean and images.removable(plan) == []
    assert lacking.images[0].state == "missing" and "fsl-edge" in lacking.images[0].detail
    assert not lacking.clean

@pytest.mark.parametrize("flavor", ["", "openstack"])
def test_every_image_is_built_from_files_the_repo_holds(flavor):
    hosts = declared.read(flavor=flavor).hosts
    built = {host: entry for host, entry in hosts.items() if entry.setup}
    assert built
    for host, entry in built.items():
        bundle = images.bundle(ROOT, host, entry.setup, entry.files)
        assert entry.setup in members(bundle), host
        images.user_data(bundle)
