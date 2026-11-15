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


SENDERS = {"sensor": ("cr-range", "suricata"), "waf": ("cr-waf", "modsecurity")}


def laid(number=2):
    return rangehost.Slot(number, rangehost.estate("10.30.0.0/16", number), "abc", 1442)


def slot_files(number=2):
    return rangehost.slot_files(ROOT, laid(number), WARGAMES, DECLARED.origins, DECLARED.default_origin,
                                "10.31.0.2", 5140, SENDERS)


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
            if url.endswith("/os-interface"):
                return {"interfaceAttachments": [{"port_id": "port-egress", "net_id": "net-platform"},
                                                 {"port_id": "port-0", "net_id": "net-mgmt"}]}
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


def test_every_slot_s_estate_and_web_network_are_its_own_slash_24s_of_the_declared_estate():
    assert [str(rangehost.estate("10.30.0.0/16", n)) for n in (1, 2, 15)] == [
        "10.30.1.0/24", "10.30.2.0/24", "10.30.15.0/24"]
    assert [str(laid(n).web) for n in (1, 2, 127)] == ["10.30.129.0/24", "10.30.130.0/24", "10.30.255.0/24"]
    with pytest.raises(Exception, match="narrower than a /16"):
        rangehost.estate("10.30.0.0/24", 1)
    with pytest.raises(Exception, match="slots 1 to 127"):
        rangehost.estate("10.30.0.0/16", 128)


def test_a_slot_s_files_put_the_edge_and_the_waf_on_its_estate_and_the_targets_behind_the_waf_alone():
    files = slot_files()
    document = yaml.safe_load(files["compose.yaml"])

    assert rangehost.addressed(document, "estate") == {"edge": "10.30.2.1", "waf": "10.30.2.247"}, (
        "a target on the estate is reached from Kali through the edge, past the WAF")
    assert rangehost.addressed(document, "web") == {
        "waf": "10.30.130.247", "board": "10.30.130.59", "corp-wp": "10.30.130.60"}
    assert sorted(document["services"]["waf"]["extra_hosts"]) == ["board:10.30.130.59", "corp-wp:10.30.130.60"]
    assert {s["container_name"] for s in document["services"].values()} == {
        f"s2-{name}" for name in document["services"]}
    assert files["fronts"] == b"board\ncorp-wp\n" and files["gateway"] == b"10.30.2.1\n"
    assert not [left for left in ("${", "@slot@", "@estate@", "@web@", "@mtu@") if left in files["compose.yaml"].decode()]


def test_one_sensor_sniffs_the_dmz_before_the_waf_and_the_web_network_after_it():
    files = slot_files()
    config = yaml.safe_load(files["sensor.yaml"].decode().removeprefix(rangehost.YAML_HEADER))
    sensor = yaml.safe_load(files["compose.yaml"])["services"]["sensor"]

    assert [capture["interface"] for capture in config["af-packet"]] == ["dmz", "web"]
    assert sensor["networks"]["estate"] == {"interface_name": "dmz"} and sensor["networks"]["web"] == {
        "interface_name": "web"}, "a sniffing interface holds no address"
    assert sensor["networks"]["mgmt"]["interface_name"] == "mgmt" and sensor["networks"]["mgmt"]["ipv4_address"]
    assert "internet" not in sensor["networks"], "the sensor watches inside the perimeter, not the Internet side"
    assert len({capture["cluster-id"] for capture in config["af-packet"]}) == 2
    assert "--af-packet" in sensor["command"]
    assert config["stats"]["interval"] == 5, "kernel_drops is read from the counters"


def test_kali_holds_every_declared_origin_address_and_the_edge_every_origin_gateway():
    files = slot_files()
    kali, edge = files["kali.ip"].decode().splitlines(), files["edge.ip"].decode().splitlines()

    assert len(kali) == sum(origin.addresses for origin in DECLARED.origins) + 1
    assert "addr add 5.188.10.10/24 dev eth0" in kali and kali[-1] == "route replace default via 5.188.10.1 dev eth0"
    assert len(edge) == len(DECLARED.origins) and "addr add 73.0.0.1/24 dev wan" in edge


def test_each_slot_s_logs_reach_the_collector_under_a_name_that_keeps_its_slot():
    one, two = slot_files(1), slot_files(2)
    relay = two["rsyslog/log-server.conf"].decode()

    assert " cr-waf modsecurity " in one["rsyslog/log-server.conf"].decode()
    assert 'File="/var/log/cr/s1/waf/audit.log"' in one["rsyslog/waf-shipper.conf"].decode()
    assert " cr-range-2 suricata " in relay and " cr-waf-2 modsecurity " in relay
    assert 'File="/var/log/cr/s2/sensor/eve.json"' in two["rsyslog/sensor-shipper.conf"].decode()
    assert 'reopenOnTruncate="on"' in two["rsyslog/sensor-shipper.conf"].decode(), "a reset empties the logs in place"
    assert relay.count('Target="10.31.0.2" Port="5140" Protocol="udp"') == 2


def test_the_log_server_names_each_log_by_the_management_address_it_came_from():
    files = slot_files(2)
    compose = yaml.safe_load(files["compose.yaml"])
    relay = files["rsyslog/log-server.conf"].decode()
    on_mgmt = rangehost.addressed(compose, rangehost.MGMT)

    for service in ("sensor", "waf"):
        shipped = files[f"rsyslog/{service}-shipper.conf"].decode()
        assert f'Target="{on_mgmt["log-server"]}" Port="514" Protocol="tcp"' in shipped
        assert f'$fromhost-ip == "{on_mgmt[service]}"' in relay
        assert compose["services"][f"{service}-shipper"]["network_mode"] == f"service:{service}", (
            "a log leaves from the management interface of the device that wrote it")
        source = compose["services"][f"{service}-shipper"]
        mounted = {str(volume).split(":")[1] for volume in source["volumes"]}
        assert f"{rangehost.LOG_FILES.format(slot=2)}/{rangehost.LOGS[service]}".startswith(
            tuple(path for path in mounted if path.startswith("/var/log/cr/")))
    assert files["uplink"] == f'{on_mgmt["log-server"]} 10.31.0.2 5140\n'.encode()


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
    assert "port-egress" in cloud.deleted and "port-0" not in cloud.deleted, (
        "once its images are pulled the range host keeps no way to the Internet, and a stack delete "
        "of the platform network finds no port of the range host on it")


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


def test_a_reset_is_the_slot_s_own_fast_reset_then_the_baseline_rules_on_the_sensor():
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

    assert ran[0] == ("", ["test", "-f", "/opt/cr/s2/compose.yaml"])
    assert ran[1] == ("", ["sudo", "sh", "/opt/cr/s2/slot.sh", "reset"])
    assert {container for container, _ in ran[2:]} == {"s2-sensor"}
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


def test_a_reset_owed_to_a_slot_whose_files_are_gone_configures_it_instead():
    cloud = Cloud()
    range_ = adapter(cloud).in_slot(2)
    range_.describe = lambda: None
    range_._shell = lambda container="": lambda argv, stdin=None, timeout=60: Ran(1, "")
    range_.configure_slot = lambda: [("cr-range", ("configured",))]

    assert range_.reset_in_place() == [("cr-range", ("configured",))], (
        "a new range host or a slot taken down while its reset was owed has no slot.sh to reset with")


def test_a_range_host_that_failed_its_setup_is_replaced_by_the_next_post(monkeypatch):
    cloud = Cloud()
    range_ = adapter(cloud)
    range_.ensure_slot()
    monkeypatch.setattr(openstack.OpenStack, "_setup_status", lambda self, server: openstack.SETUP_FAILED)

    range_.ensure_slot()

    assert len(cloud.booted()) == 2 and "srv-1" in cloud.deleted, (
        "a setup that failed for a passing reason, such as a pull from GHCR, is tried again on a new range host")


def test_the_waf_s_audit_log_is_forwarded_from_where_modsecurity_writes_it():
    import re

    written = re.search(r"^SecAuditLog\s+(\S+)", (ROOT / "deploy/waf/modsecurity.conf").read_text(), re.M)[1]
    document = rangehost.compose(ROOT, laid(1), WARGAMES)
    mounted = dict(volume.split(":")[1::-1] for volume in document["services"]["waf"]["volumes"])

    assert mounted.get(written) == f"{rangehost.LOG_FILES.format(slot=1)}/{rangehost.LOGS['waf']}"


def test_a_slot_s_compose_is_parsed_once_and_again_only_when_its_files_change(tmp_path, monkeypatch):
    import shutil

    for name in (rangehost.TEMPLATE, rangehost.SETUP, *(rangehost.COMPOSE.format(wargame=w) for w in WARGAMES)):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, tmp_path / name)
    parsed = []
    real = rangehost.yaml.safe_load
    monkeypatch.setattr(rangehost.yaml, "safe_load", lambda text: parsed.append(1) or real(text))

    first = rangehost.compose(tmp_path, laid(3), WARGAMES)
    first["services"].clear()
    again = rangehost.compose(tmp_path, laid(3), WARGAMES)
    once = len(parsed)
    template = tmp_path / rangehost.TEMPLATE
    template.write_text(template.read_text().replace("mem_limit: 64m", "mem_limit: 65m"))
    changed = rangehost.compose(tmp_path, laid(3), WARGAMES)

    assert once == 1 + len(WARGAMES), "the second read of an unchanged slot parsed its YAML again"
    assert again["services"], "a caller's change to the document reached the next caller"
    assert changed["services"]["edge"]["mem_limit"] == "65m" and len(parsed) > once


def test_reading_the_slots_plans_does_not_rebuild_the_range_bundle(monkeypatch):
    built = []
    real = rangehost.bundle
    monkeypatch.setattr(rangehost, "bundle", lambda *a, **k: built.append(1) or real(*a, **k))
    range_of_four = adapter(Cloud(), slots=4)

    for _ in range(3):
        range_of_four.plan_slots()

    assert len(built) <= 1, f"every readiness read rebuilt the range bundle: {len(built)} builds"


def test_the_range_host_finds_its_own_name_in_etc_hosts_before_a_slot_comes_up():
    script = (ROOT / rangehost.SLOT_SCRIPT).read_text()
    prepare = script[script.index("\nprepare() {"):script.index("\n}\n", script.index("\nprepare() {"))]

    assert "printf '127.0.1.1 %s\\n' \"$(hostname)\" >> /etc/hosts" in script
    assert prepare.lstrip("\n").splitlines()[1].strip() == "named", (
        "sudo looks up the host's own name on every command; with no DNS and no /etc/hosts line, "
        "systemd-resolved's answer took 21.8 s on a range host with eight slots, so every docker exec "
        "the platform sent waited that long")


def test_bringing_a_slot_up_restarts_its_log_server_and_shippers_on_the_files_just_written():
    script = (ROOT / rangehost.SLOT_SCRIPT).read_text()
    up = script[script.index("\nup() {"):script.index("\n}\n", script.index("\nup() {"))]

    assert "--force-recreate --no-deps" in up and "$(logging)" in up, (
        "rsyslog reads its config at start and a bind-mounted file keeps the inode it was created with; "
        "re-rendered in place, the log server kept naming 172.29.N.12 as the old estate sensor and the WAF's "
        "audit log reached Elasticsearch as Suricata's")
    assert "grep -e '^log-server$' -e '-shipper$'" in script
