import base64
import itertools
import pathlib
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from range import declared, images, openstack
from range.ports import RangeUnavailable

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = {"id": "img-ubuntu", "name": "ubuntu-24.04", "status": "active"}

class Cloud:
    def __init__(self):
        self.images = [dict(BASE)]
        self.servers = []
        self.consoles = {}
        self.calls = []
        self.ids = itertools.count(1)

    def __call__(self, call, body=None):
        verb, url = call.split(" ", 1)
        parts = urlsplit(url)
        path, query = parts.path.strip("/"), parse_qs(parts.query)
        self.calls.append((verb, path, body))
        if verb == "GET" and path == "v2/images":
            return {"images": [i for i in self.images if i["name"] == query["name"][0]]}
        if verb == "GET" and path == "v2.1/flavors":
            return {"flavors": [{"id": "f-1", "name": "m1.tiny"}, {"id": "f-2", "name": "m1.small"}]}
        if verb == "GET" and path == "v2.1/servers/detail":
            return {"servers": self.servers}
        if verb == "POST" and path == "v2.1/servers":
            made = dict(body["server"], id=f"srv-{next(self.ids)}", status="BUILD",
                        created="2026-10-01T12:00:00Z", addresses={})
            self.servers.append(made)
            return {"server": {"id": made["id"]}}
        if verb == "POST" and path.endswith("/action"):
            server = path.split("/")[2]
            if "os-getConsoleOutput" in body:
                return {"output": self.consoles.get(server, "")}
            if "os-stop" in body:
                next(s for s in self.servers if s["id"] == server)["status"] = "SHUTOFF"
                return {}
            made = body["createImage"]
            self.images.append({"id": f"img-{next(self.ids)}", "name": made["name"],
                                "status": "queued", **made["metadata"]})
            return {}
        if verb == "DELETE" and path.startswith("v2.1/servers/"):
            self.servers = [s for s in self.servers if s["id"] != path.rsplit("/", 1)[1]]
            return {}
        if verb == "DELETE" and path.startswith("v2/images/"):
            self.images = [i for i in self.images if i["id"] != path.rsplit("/", 1)[1]]
            return {}
        raise AssertionError(call)

    def writes(self):
        return [(verb, path) for verb, path, body in self.calls
                if verb != "GET" and "os-getConsoleOutput" not in (body or {})]

    def builder(self, host):
        return next(s for s in self.servers if s["metadata"][images.BUILDS] == host)

    def finish(self, host, worked=True):
        server = self.builder(host)
        server["status"] = "ACTIVE"
        digest = server["metadata"][images.BUNDLE]
        self.consoles[server["id"]] = (
            f"setup done\n{images.READY} {digest}\n" if worked
            else f"E: Unable to locate package\n{images.FAILED} {digest}\n"
        )

SPEC = openstack.Cloud(
    keystone="http://keystone:5000", neutron="http://neutron:9696",
    nova="http://nova:8774/v2.1", glance="http://glance:9292", project="fsl",
    user="fsl", ssh_user="ubuntu", ssh_key="/keys/fsl",
)

@pytest.fixture
def cloud():
    return Cloud()

def adapter(cloud, network="net-platform"):
    build = openstack.Build(source=str(ROOT), base_image="ubuntu-24.04",
                            flavor="m1.small", network=network)
    return openstack.OpenStack(declared.read(), SPEC, get=cloud, build=build)

HOSTS = sorted(declared.read().hosts)

def test_an_empty_project_boots_one_builder_per_declared_image(cloud):
    plan = adapter(cloud).ensure_images()

    assert sorted(s["metadata"][images.BUILDS] for s in cloud.servers) == HOSTS
    assert {i.state for i in plan.images} == {"building"}
    for server in cloud.servers:
        assert server["name"] == images.BUILDER + server["metadata"][images.BUILDS]
        assert server["imageRef"] == "img-ubuntu" and server["flavorRef"] == "f-2"
        assert server["networks"] == [{"uuid": "net-platform"}]
        assert server["config_drive"] is True
        config = yaml.safe_load(base64.b64decode(server["user_data"]).decode())
        assert server["metadata"][images.BUNDLE] in config["runcmd"][0][-1]

def test_a_host_builds_on_its_own_base_image_when_it_declares_one(cloud):
    from range.declared import Declaration, Host

    cloud.images.append({"id": "img-kali", "name": "kali-rolling", "status": "active"})
    decl = Declaration(
        roles={"attacker": "fsl-kali"},
        hosts={"fsl-kali": Host(setup="deploy/kali/motd", files=("deploy/kali/motd",),
                                base="kali-rolling", segments=("internet", "mgmt"))},
    )
    build = openstack.Build(source=str(ROOT), base_image="ubuntu-24.04",
                            flavor="m1.small", network="net-platform")

    openstack.OpenStack(decl, SPEC, get=cloud, build=build).ensure_images()

    assert cloud.builder("fsl-kali")["imageRef"] == "img-kali", (
        "a host built on Ubuntu's base could not be Kali; the declared base wins"
    )

def test_building_needs_a_network_that_reaches_the_internet_and_names_its_setting(cloud):
    with pytest.raises(RangeUnavailable, match="FSL_OPENSTACK_BUILD_NETWORK"):
        adapter(cloud, network="").ensure_images()

    assert cloud.writes() == []

def test_a_builder_still_running_is_left_alone(cloud):
    adapter(cloud).ensure_images()
    written = len(cloud.writes())

    adapter(cloud).ensure_images()

    assert len(cloud.writes()) == written

def test_a_builder_that_finished_is_stopped_and_then_snapshotted(cloud):
    adapter(cloud).ensure_images()
    cloud.finish("fsl-waf")
    adapter(cloud).ensure_images()

    plan = adapter(cloud).ensure_images()

    made = [i for i in cloud.images if i["name"] == "fsl-waf"]
    assert len(made) == 1
    assert made[0][images.BUNDLE] == cloud.builder("fsl-waf")["metadata"][images.BUNDLE]
    assert next(i for i in plan.images if i.host == "fsl-waf").state == "saving"

def test_the_builder_goes_once_its_image_is_active(cloud):
    adapter(cloud).ensure_images()
    cloud.finish("fsl-waf")
    adapter(cloud).ensure_images()
    adapter(cloud).ensure_images()
    next(i for i in cloud.images if i["name"] == "fsl-waf")["status"] = "active"

    plan = adapter(cloud).ensure_images()

    assert "fsl-waf" not in {s["metadata"][images.BUILDS] for s in cloud.servers}
    waf = next(i for i in plan.images if i.host == "fsl-waf")
    assert waf.state == "ready" and waf.builder == ""

def test_a_builder_whose_setup_failed_is_neither_stopped_nor_snapshotted(cloud):
    adapter(cloud).ensure_images()
    cloud.finish("fsl-wg-board", worked=False)

    plan = adapter(cloud).ensure_images()

    assert not [i for i in cloud.images if i["name"] == "fsl-wg-board"]
    assert cloud.builder("fsl-wg-board")["status"] == "ACTIVE"
    board = next(i for i in plan.images if i.host == "fsl-wg-board")
    assert board.state == "failed" and "Unable to locate package" in board.detail

def test_cleaning_removes_failed_builders_and_stale_images_but_not_ready_ones(cloud):
    adapter(cloud).ensure_images()
    cloud.finish("fsl-wg-board", worked=False)
    cloud.finish("fsl-waf")
    adapter(cloud).ensure_images()
    adapter(cloud).ensure_images()
    next(i for i in cloud.images if i["name"] == "fsl-waf")["status"] = "active"
    cloud.images.append({"id": "img-old", "name": "fsl-wg-board", "status": "active",
                         images.BUNDLE: "0000000000000000"})

    removed = adapter(cloud).clean_images()

    assert ("image", "img-old") in removed
    assert ("server", cloud_id_of(removed, "server")) in removed
    assert "fsl-wg-board" not in {s["metadata"][images.BUILDS] for s in cloud.servers}
    assert [i["id"] for i in cloud.images if i["name"] == "fsl-waf"]

def cloud_id_of(removed, kind):
    return next(ident for k, ident in removed if k == kind)

def test_planning_only_reads(cloud):
    adapter(cloud).plan_images()

    assert cloud.writes() == []

def test_a_base_image_the_cloud_lacks_is_named(cloud):
    cloud.images = []

    with pytest.raises(RangeUnavailable, match="ubuntu-24.04"):
        adapter(cloud).ensure_images()

def test_the_image_calls_send_the_documented_api_fields():
    reference = {
        openstack.IMAGES: "https://docs.openstack.org/api-ref/image/v2/#list-images",
        openstack.DELETE_IMAGE: "https://docs.openstack.org/api-ref/image/v2/#delete-image",
        openstack.FLAVORS: "https://docs.openstack.org/api-ref/compute/#list-flavors",
        openstack.ACTION: "https://docs.openstack.org/api-ref/compute/#create-image-createimage-action",
        openstack.DELETE_SERVER: "https://docs.openstack.org/api-ref/compute/#delete-server",
    }
    source = pathlib.Path(openstack.__file__).read_text()

    for field in ('"createImage"', '"os-getConsoleOutput"', '"os-stop"', '"output"', '"status"',
                  '"metadata"', '"config_drive"', '"user_data"', '"flavorRef"', '"imageRef"'):
        assert field in source, f"{field} is read or sent and checked against {reference}"
