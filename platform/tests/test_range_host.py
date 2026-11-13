import base64
import io
import ipaddress
import pathlib
import tarfile

import pytest
import yaml

from range import declared, fabric, openstack, rangehost, slot
from range.ports import Drifted, Ran

ROOT = pathlib.Path(__file__).resolve().parents[2]
DECLARED = declared.read()
WARGAMES = DECLARED.hosts[DECLARED.range_host].wargames
MANAGEMENT = {"cr-mgmt": [{"addr": "10.31.0.40", "OS-EXT-IPS:type": "fixed", "version": 4}]}
PLATFORM = {"id": "srv-platform", "name": "cr-platform", "status": "ACTIVE", "metadata": {},
            "addresses": {"cr-mgmt": [{"addr": "10.31.0.2", "OS-EXT-IPS:type": "fixed", "version": 4}]}}


def laid(number=2):
    return rangehost.Slot(number, rangehost.estate("10.30.0.0/16", number), "abc", 1442)


class Cloud:
    def __init__(self):
        self.servers = [dict(PLATFORM)]
        self.ports, self.calls, self.deleted = [], [], []
        self.networks = [{"id": "net-mgmt", "name": "cr-mgmt", "tags": ["cr.segment.id=mgmt"]}]
        self.subnets = [{"id": "sub-mgmt", "network_id": "net-mgmt", "cidr": "10.31.0.0/24",
                         "gateway_ip": None, "enable_dhcp": True, "name": "cr-mgmt"}]
        self.groups = [{"id": f"g-{name}", "name": name, "security_group_rules": []}
                       for name in fabric.GROUPS]
        self.images = []

    def __call__(self, call, body=None):
        verb, url = call.split(" ", 1)
        self.calls.append((verb, url, body))
        if verb == "GET":
            for key, held in (("/servers/detail", ("servers", self.servers)), ("/networks", ("networks", self.networks)),
                              ("/subnets", ("subnets", self.subnets)), ("/ports", ("ports", self.ports)),
                              ("security-groups", ("security_groups", self.groups)),
                              ("/flavors", ("flavors", [{"id": "f-range", "name": "dba.range"}])),
                              ("keypairs", ("keypairs", []))):
                if key in url:
                    return {held[0]: held[1]}
            if "/images?name=" in url:
                return {"images": [{"id": "img-ubuntu", "status": "active"}]}
            if "/images?owner=" in url:
                return {"images": self.images}
        if verb == "POST" and url.endswith("/ports"):
            port = {"id": f"port-{len(self.ports)}", "device_id": "", "device_owner": "", **body["port"]}
            self.ports.append(port)
            return {"port": port}
        if verb == "POST" and url.endswith("/servers"):
            made = body["server"]
            self.servers.append({"id": f"srv-{len(self.servers)}", "name": made["name"], "status": "ACTIVE",
                                 "metadata": made["metadata"], "addresses": MANAGEMENT})
            return {"server": {"id": self.servers[-1]["id"]}}
        if verb == "DELETE":
            ident = url.rsplit("/", 1)[1]
            self.deleted.append(ident)
            self.servers = [s for s in self.servers if s["id"] != ident]
            self.ports = [p for p in self.ports if p["id"] != ident]
            return {}
        return {}

    def booted(self):
        return [body["server"] for verb, url, body in self.calls if verb == "POST" and url.endswith("/servers")]


def adapter(cloud, slots=2, tag="abc"):
    spec = openstack.Cloud(keystone="k", neutron="http://neutron", nova="http://nova", project="p", user="u",
                           ssh_user="ubuntu", ssh_key="/nonexistent", glance="http://glance")
    build = openstack.Build(source=str(ROOT), base_image="ubuntu-24.04", flavor="dba.range",
                            inside={"estate": "10.30.0.0/16", "mgmt": "10.31.0.0/24"}, mtu=1442,
                            network="net-platform", platform="srv-platform", image_tag=tag, slots=slots)
    return openstack.OpenStack(DECLARED, spec, cloud, build=build)


SET_UP = openstack.OpenStack._setup_status


@pytest.fixture(autouse=True)
def forgotten(monkeypatch):
    openstack.forget()
    monkeypatch.setattr(openstack.OpenStack, "_setup_status", lambda self, server: server.get("status"))
    yield
    openstack.forget()


def test_every_slot_s_estate_is_its_own_slash_24_of_the_declared_estate():
    assert [str(rangehost.estate("10.30.0.0/16", n)) for n in (1, 2, 15)] == [
        "10.30.1.0/24", "10.30.2.0/24", "10.30.15.0/24"]
    with pytest.raises(Exception, match="narrower than a /16"):
        rangehost.estate("10.30.0.0/24", 1)


def test_a_slot_s_files_put_the_targets_the_waf_and_the_edge_on_its_own_estate():
    files = rangehost.slot_files(ROOT, laid(2), WARGAMES, DECLARED.origins, DECLARED.default_origin, "")
    document = yaml.safe_load(files["compose.yaml"])

    assert rangehost.addressed(document, "estate") == {
        "edge": "10.30.2.1", "waf": "10.30.2.247", "board": "10.30.2.59", "corp-wp": "10.30.2.60"}
    assert {s["container_name"] for s in document["services"].values()} == {
        f"s2-{name}" for name in document["services"]}
    assert files["fronts"] == b"board\ncorp-wp\n" and files["gateway"] == b"10.30.2.1\n"
    assert not [left for left in ("${", "@slot@", "@estate@", "@mtu@") if left in files["compose.yaml"].decode()]


def test_the_estate_sensor_sees_only_what_the_wargame_host_s_nic_saw():
    files = rangehost.slot_files(ROOT, laid(2), WARGAMES, DECLARED.origins, DECLARED.default_origin, "")
    config = yaml.safe_load(files["estate-sensor.yaml"].decode().removeprefix(rangehost.YAML_HEADER))
    [capture] = config["af-packet"]

    assert capture["interface"] == "s2-estate"
    assert capture["bpf-filter"] == "host 10.30.2.59 or host 10.30.2.60", (
        "the estate bridge also carries the edge's traffic to the WAF, which the wargame host's NIC never saw")
    assert config["stats"]["interval"] == 5, "kernel_drops is read from the counters"


def test_kali_holds_every_declared_origin_address_and_the_edge_every_origin_gateway():
    files = rangehost.slot_files(ROOT, laid(2), WARGAMES, DECLARED.origins, DECLARED.default_origin, "")
    kali, edge = files["kali.ip"].decode().splitlines(), files["edge.ip"].decode().splitlines()

    assert len(kali) == sum(origin.addresses for origin in DECLARED.origins) + 1
    assert "addr add 5.188.10.10/24 dev eth0" in kali and kali[-1] == "route replace default via 5.188.10.1 dev eth0"
    assert len(edge) == len(DECLARED.origins) and "addr add 73.0.0.1/24 dev wan" in edge


def test_each_slot_s_logs_reach_the_collector_under_a_name_that_keeps_its_slot():
    one = rangehost.forwarding(laid(1), "10.31.0.2", 5140, {"waf": ("cr-waf", "modsecurity")})
    two = rangehost.forwarding(laid(2), "10.31.0.2", 5140, {"edge-sensor": ("cr-edge", "suricata")})

    assert " cr-waf %APP-NAME%" in one and 'File="/var/log/cr/s1/waf/audit.log"' in one
    assert " cr-edge-2 %APP-NAME%" in two and 'File="/var/log/cr/s2/edge/eve.json"' in two
    assert 'reopenOnTruncate="on"' in two, "a reset empties the logs in place"


def test_the_range_host_boots_once_from_the_stock_image_with_its_bundle_and_both_ports():
    cloud = Cloud()
    range_ = adapter(cloud)

    for one in range_.every_slot():
        one.ensure_slot()

    [server] = cloud.booted()
    assert server["imageRef"] == "img-ubuntu" and server["flavorRef"] == "f-range"
    assert server["networks"] == [{"port": "port-0"}, {"uuid": "net-platform"}]
    assert cloud.ports[0]["security_groups"] == ["g-cr-mgmt"] and server["security_groups"] == [{"name": "cr-egress"}]
    assert server["metadata"][slot.HOST] == "cr-range" and server["metadata"][slot.TAG] == "abc"
    document = yaml.safe_load(base64.b64decode(server["user_data"]).decode().removeprefix("#cloud-config\n"))
    packed = base64.b64decode(document["write_files"][0]["content"])
    with tarfile.open(fileobj=io.BytesIO(packed)) as tar:
        assert {"setup.sh", "images.txt", "pristine.yaml", "daemon.json"} <= set(tar.getnames())


def test_a_range_host_still_setting_itself_up_is_not_active(monkeypatch):
    monkeypatch.setattr(openstack.OpenStack, "_setup_status", SET_UP)
    cloud = Cloud()
    range_ = adapter(cloud)
    range_.ensure_slot()
    range_._shell = lambda container="": lambda argv, stdin=None, timeout=60: Ran(0, "setting-up\n")

    assert range_.plan_slot().standing[0][2] == openstack.SETTING_UP and not range_.plan_slot().active
    range_._shell = lambda container="": lambda argv, stdin=None, timeout=60: Ran(0, "ready\n")
    assert range_.plan_slot().active


def test_a_range_host_on_an_older_tag_is_replaced_and_a_current_one_is_left():
    cloud = Cloud()
    adapter(cloud, tag="old").ensure_slot()
    current = adapter(cloud, tag="new")

    assert current.plan_slot().stale == ("cr-range",)
    current.ensure_slot(renew=False)
    assert len(cloud.booted()) == 1
    current.ensure_slot()
    assert len(cloud.booted()) == 2 and cloud.booted()[-1]["metadata"][slot.TAG] == "new"
    assert "srv-1" in cloud.deleted


def test_a_command_for_a_role_runs_in_its_slot_s_container_through_the_range_host():
    cloud = Cloud()
    range_ = adapter(cloud).in_slot(2)
    range_.ensure_slot()
    sent = []
    range_._address = lambda host: "10.31.0.40"
    range_._config = lambda written, address: written
    openstack.execute.__globals__  # noqa
    real = openstack.execute

    def caught(host, command, stdin, timeout):
        sent.append(command[-1])
        raise openstack.RangeUnavailable("caught")

    openstack.execute = caught
    try:
        with pytest.raises(openstack.RangeUnavailable):
            range_.runner("attacker")(["curl", "http://board.com/"])
        with pytest.raises(openstack.RangeUnavailable):
            range_.runner("wargames")(["true"])
    finally:
        openstack.execute = real

    assert sent[0].startswith("sudo docker exec s2-kali sh -c")
    assert sent[1].startswith("sh -c ")


def test_what_the_vm_range_left_is_listed_and_removed_servers_first():
    cloud = Cloud()
    adapter(cloud).ensure_slot()
    cloud.servers.append({"id": "srv-old-kali", "name": "cr-kali-2", "status": "ACTIVE",
                          "metadata": {"cr_host": "cr-kali", "cr_slot": "2"}, "addresses": {}})
    cloud.networks.append({"id": "net-inet-2", "name": "cr-internet-2", "tags": ["cr.segment.id=internet", "cr.slot=2"]})
    cloud.ports.append({"id": "port-old", "name": "cr-kali-2.internet", "network_id": "net-inet-2",
                        "device_id": "", "device_owner": ""})
    cloud.groups.append({"id": "g-old", "name": "cr-range", "security_group_rules": []})
    cloud.images = [{"id": "img-kali", "name": "cr-kali", "cr_bundle": "x"}, {"id": "img-own", "name": "mine"}]
    range_ = adapter(cloud)

    assert {ident for _, ident, _ in range_.plan_leftovers()} == {
        "srv-old-kali", "net-inet-2", "port-old", "g-old", "img-kali"}
    removed = range_.clean_leftovers()

    assert removed[0] == ("server", "srv-old-kali")
    assert [kind for kind, _ in removed[1:]] == ["port", "network", "group", "image"]
    assert "srv-1" not in cloud.deleted and "img-own" not in cloud.deleted, "the range host and other images stay"


def test_a_reset_is_the_slot_s_own_fast_reset_then_the_baseline_rules_on_both_sensors():
    cloud = Cloud()
    range_ = adapter(cloud).in_slot(2)
    range_.ensure_slot()
    ran = []

    def shell(container=""):
        def run(argv, stdin=None, timeout=60):
            ran.append((container, argv[:4]))
            return Ran(0, '{"return":"OK"}' if "reload-rules" in argv else "")
        return run

    range_._shell = shell
    range_.describe = lambda: None
    done = range_.reset_in_place()

    assert ran[0] == ("", ["sudo", "sh", "/opt/cr/s2/slot.sh", "reset"])
    assert {container for container, _ in ran[1:]} == {"s2-edge-sensor", "s2-estate-sensor"}
    assert done[0] == ("cr-range", ("reset slot 2",)) and range_.reset_slot() == [], (
        "nothing is rebuilt by Nova: the slot's own containers are recreated on the range host")


def test_taking_a_slot_down_leaves_the_range_host_and_its_other_slots():
    cloud = Cloud()
    range_ = adapter(cloud).in_slot(2)
    range_.ensure_slot()
    ran = []
    range_._shell = lambda container="": lambda argv, stdin=None, timeout=60: ran.append(argv) or Ran(0, "")

    assert range_.teardown_slot() == [("project", "s2")]
    assert ran == [rangehost.down(laid(2))] and not cloud.deleted
    with pytest.raises(Drifted):
        range_._shell = lambda container="": lambda argv, stdin=None, timeout=60: Ran(1, "busy")
        range_.teardown_slot()
