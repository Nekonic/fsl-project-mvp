import base64
import io
import pathlib
import random
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

def test_a_bundle_keeps_whether_a_file_may_be_executed(source):
    (source / "waf" / "site.conf").chmod(0o755)

    assert members(packed(source))["waf/site.conf"].mode == 0o755

def test_the_same_files_give_the_same_digest_and_any_change_gives_another(source):
    first = packed(source).digest
    assert packed(source).digest == first

    (source / "waf" / "site.conf").write_text("server { listen 81; }\n")
    assert packed(source).digest != first

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

def test_a_bundle_too_big_for_nova_user_data_is_refused(source):
    (source / "waf" / "blob").write_bytes(random.Random(0).randbytes(60_000))

    with pytest.raises(RangeUnavailable, match="65535"):
        images.user_data(packed(source))

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

def test_nothing_built_yet_is_missing():
    found, plan = state()

    assert found.state == "missing" and not plan.clean

def test_a_builder_still_running_is_building():
    found, _ = state(builders=[builder()])

    assert found.state == "building" and found.builder == "srv-1"

def test_a_builder_that_said_it_finished_is_built():
    found, _ = state(builders=[builder()],
                     consoles={"srv-1": f"...\n{images.READY} d1\nubuntu login:\n"})

    assert found.state == "built"

def test_a_builder_already_being_stopped_is_left_to_stop():
    stopping = {**builder(), "OS-EXT-STS:task_state": "powering-off"}
    found, _ = state(builders=[stopping], consoles={"srv-1": f"{images.READY} d1\n"})

    assert found.state == "building" and "powering-off" in found.detail

def test_a_builder_whose_setup_failed_says_why():
    found, _ = state(builders=[builder()],
                     consoles={"srv-1": f"E: Unable to locate package nginx\n{images.FAILED} d1\n"})

    assert found.state == "failed"
    assert "Unable to locate package nginx" in found.detail

def test_the_ready_line_of_another_bundle_does_not_count():
    found, _ = state(builders=[builder()], consoles={"srv-1": f"{images.READY} d0\n"})

    assert found.state == "building"

def test_a_stopped_builder_is_ready_to_be_snapshotted():
    found, _ = state(builders=[builder("SHUTOFF")])

    assert found.state == "stopped"

def test_an_image_being_saved_is_saving():
    found, _ = state(images_=[image("saving")], builders=[builder("SHUTOFF")])

    assert found.state == "saving"

def test_an_active_image_of_this_bundle_is_ready_and_the_builder_left_is_not_clean():
    found, plan = state(images_=[image()], builders=[builder("SHUTOFF")])

    assert found.state == "ready" and found.image == "img-1"
    assert found.builder == "srv-1" and not plan.clean

def test_ready_with_no_builder_left_is_clean():
    _, plan = state(images_=[image()])

    assert plan.clean

def test_an_image_of_another_bundle_is_left_over_and_does_not_stand_in():
    found, plan = state(images_=[image(bundle="d0", ident="img-old")])

    assert found.state == "missing"
    assert [(kind, ident) for kind, ident, _ in plan.leftovers] == [("image", "img-old")]

def test_a_builder_of_another_bundle_is_left_over():
    found, plan = state(builders=[builder(bundle="d0", ident="srv-old")])

    assert found.state == "missing"
    assert [(kind, ident) for kind, ident, _ in plan.leftovers] == [("server", "srv-old")]

def test_what_cleaning_removes_is_leftovers_and_failures_never_a_ready_image():
    plan = images.plan(
        (BUNDLE, images.Bundle("fsl-wiki", "wiki/setup.sh", "w1", b"")),
        [image(), image(bundle="d0", ident="img-old")],
        [builder(bundle="w1", ident="srv-wiki", host="fsl-wiki")],
        {"srv-wiki": f"Traceback\n{images.FAILED} w1\n"},
    )

    assert images.removable(plan) == [("image", "img-old"), ("server", "srv-wiki")]

def test_every_host_with_an_image_is_one_the_range_gives_a_role():
    declaration = declared.read()

    assert declaration.hosts
    assert set(declaration.hosts) <= set(declaration.roles.values())

def test_every_image_is_built_from_files_the_repo_holds():
    for host, entry in declared.read().hosts.items():
        bundle = images.bundle(ROOT, host, entry.setup, entry.files)
        assert entry.setup in members(bundle), host
        images.user_data(bundle)

def test_a_host_with_an_image_and_no_role_is_refused(tmp_path):
    document = yaml.safe_load((ROOT / "platform/range/declaration.yaml").read_text())
    document["hosts"]["fsl-stray"] = {"setup": "stray.sh"}
    path = tmp_path / "declaration.yaml"
    path.write_text(yaml.safe_dump(document))

    with pytest.raises(ValueError, match="fsl-stray"):
        declared.read(path)
