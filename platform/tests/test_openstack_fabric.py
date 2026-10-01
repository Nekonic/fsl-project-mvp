import itertools
import stat

import pytest

from range import declared, fabric, openstack
from range.ports import Drifted, RangeUnavailable

class Neutron:
    def __init__(self):
        self.networks, self.subnets, self.keypairs, self.ports = [], [], [], []
        self.calls = []
        self.refuse_tags = False
        self.ids = itertools.count(1)

    def __call__(self, call, body=None):
        verb, url = call.split(" ", 1)
        path = url.split("://", 1)[1].split("/", 1)[1]
        self.calls.append((verb, path))
        resource = path.split("?", 1)[0]
        if verb == "GET":
            if resource == "v2.0/networks":
                return {"networks": self.networks}
            if resource == "v2.0/subnets":
                return {"subnets": self.subnets}
            if resource == "v2.0/ports":
                network = path.rsplit("=", 1)[1]
                return {"ports": [p for p in self.ports if p["network_id"] == network]}
            if resource == "os-keypairs":
                return {"keypairs": [{"keypair": k} for k in self.keypairs]}
        if verb == "POST" and resource == "v2.0/networks":
            created = dict(body["network"], id=f"net-{next(self.ids)}", tags=[])
            self.networks.append(created)
            return {"network": created}
        if verb == "PUT" and resource.endswith("/tags"):
            if self.refuse_tags:
                raise RangeUnavailable(f"PUT {url} answered 500")
            network = next(n for n in self.networks if n["id"] == resource.split("/")[2])
            network["tags"] = list(body["tags"])
            return {"tags": network["tags"]}
        if verb == "POST" and resource == "v2.0/subnets":
            made = [dict(s, id=f"sub-{next(self.ids)}") for s in body["subnets"]]
            for subnet in made:
                subnet.setdefault("gateway_ip", subnet["cidr"].replace("0/24", "1"))
            self.subnets += made
            return {"subnets": made}
        if verb == "POST" and resource == "os-keypairs":
            self.keypairs.append(dict(body["keypair"]))
            return {"keypair": body["keypair"]}
        if verb == "DELETE":
            kind, ident = resource.rsplit("/", 2)[-2:]
            pool = {"networks": self.networks, "subnets": self.subnets,
                    "os-keypairs": self.keypairs}[kind]
            pool[:] = [r for r in pool if r.get("id", r.get("name")) != ident]
            return {}
        raise AssertionError(call)

    def writes(self):
        return [call for call in self.calls if call[0] != "GET"]

@pytest.fixture
def cloud():
    return Neutron()

@pytest.fixture
def adapter(cloud, tmp_path):
    spec = openstack.Cloud(
        keystone="http://keystone:5000", neutron="http://neutron:9696",
        nova="http://nova:8774", project="fsl", user="fsl",
        ssh_user="ubuntu", ssh_key=str(tmp_path / "ssh" / "id_ed25519"),
    )
    return openstack.OpenStack(declared.read(), spec, get=cloud)

def test_building_on_an_empty_project_makes_the_whole_fabric(cloud, adapter):
    adapter.ensure_fabric()

    tags = sorted(t for n in cloud.networks for t in n["tags"])
    assert tags == [f"{fabric.TAG}={s}" for s in ("estate", "internet", "mgmt")]
    assert len(cloud.subnets) == 32
    assert [k["name"] for k in cloud.keypairs] == [fabric.KEYPAIR]
    assert [c for c in cloud.writes() if c == ("POST", "v2.0/subnets")] == [("POST", "v2.0/subnets")], (
        "thirty-two subnets went out one call each; a single bulk create is "
        "one answer to check and one quota refusal to name"
    )

def test_the_platform_makes_its_own_key_and_keeps_it_private(cloud, adapter, tmp_path):
    adapter.ensure_fabric()

    private = tmp_path / "ssh" / "id_ed25519"
    assert stat.S_IMODE(private.stat().st_mode) == 0o600
    assert cloud.keypairs[0]["public_key"].split()[:2] == (
        private.with_name("id_ed25519.pub").read_text().split()[:2]
    )

def test_building_twice_only_reads_the_second_time(cloud, adapter):
    adapter.ensure_fabric()
    written = len(cloud.writes())
    adapter.ensure_fabric()

    assert len(cloud.writes()) == written

def test_drift_is_refused_before_anything_is_written(cloud, adapter):
    adapter.ensure_fabric()
    cloud.subnets[0]["enable_dhcp"] = True
    written = len(cloud.writes())

    with pytest.raises(Drifted, match="dhcp is on"):
        adapter.ensure_fabric()
    assert len(cloud.writes()) == written

def test_a_network_that_could_not_be_tagged_is_not_left_behind(cloud, adapter):
    cloud.refuse_tags = True

    with pytest.raises(RangeUnavailable):
        adapter.ensure_fabric()
    assert cloud.networks == [], (
        "an untagged network is invisible to the range and would be built "
        "again beside itself on the next try"
    )

def test_taking_it_down_is_refused_while_a_server_stands_on_it(cloud, adapter):
    adapter.ensure_fabric()
    internet = next(n for n in cloud.networks if f"{fabric.TAG}=internet" in n["tags"])
    cloud.ports.append({"network_id": internet["id"], "device_owner": "compute:nova"})

    with pytest.raises(RangeUnavailable, match="fsl-internet"):
        adapter.teardown_fabric()
    assert len(cloud.subnets) == 32

def test_taking_it_down_removes_only_what_the_fabric_owns(cloud, adapter):
    cloud.networks.append({"id": "net-scratch", "name": "tenant-scratch", "tags": []})
    adapter.ensure_fabric()
    adapter.teardown_fabric()

    assert [n["id"] for n in cloud.networks] == ["net-scratch"]
    assert cloud.subnets == [] and cloud.keypairs == []

def test_planning_only_reads(cloud, adapter):
    plan = adapter.plan_fabric()

    assert not cloud.writes()
    assert plan.networks == ("internet", "estate", "mgmt")

def test_management_is_built_with_no_gateway(cloud, adapter):
    adapter.ensure_fabric()
    mgmt = next(n for n in cloud.networks if f"{fabric.TAG}=mgmt" in n["tags"])

    [subnet] = [s for s in cloud.subnets if s["network_id"] == mgmt["id"]]
    assert subnet["gateway_ip"] is None and subnet["enable_dhcp"] is True
