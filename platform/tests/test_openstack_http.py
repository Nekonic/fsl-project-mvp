import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from range import openstack
from range.ports import RangeUnavailable

SUBNET = {"subnets": [{"cidr": "5.188.10.0/24", "gateway_ip": "5.188.10.1"}]}

class Cloud:
    def __init__(self):
        self.seen = []
        self.tokens = 0
        self.expire_after = None
        self.always_401 = False
        self.logins = []
        self.refuse_logins = False

    def handler(self):
        cloud = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, headers=None):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _login(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                user = body["auth"]["identity"]["password"]["user"]["name"]
                cloud.logins.append(user)

            def do_POST(self):
                self._login()
                if cloud.refuse_logins:
                    return self._send(401, {"error": {
                        "code": 401, "title": "Unauthorized",
                        "message": "The account is disabled for user: fsl",
                    }})
                cloud.tokens += 1
                self._send(201, {"token": {}}, {"X-Subject-Token": f"tok{cloud.tokens}"})

            def do_GET(self):
                cloud.seen.append((self.path, dict(self.headers)))
                if cloud.always_401:
                    return self._send(401, {"error": {"message": "nope"}})
                if cloud.expire_after is not None and len(
                    [s for s in cloud.seen if "/v2.0/" in s[0] or "/servers" in s[0]]
                ) > cloud.expire_after:
                    cloud.expire_after = None
                    return self._send(401, {"error": {"message": "token expired"}})
                if "/v2.0/subnets" in self.path:
                    return self._send(200, SUBNET)
                if "/servers/detail" in self.path:
                    return self._send(200, {"servers": []})
                if "/v2.0/networks" in self.path:
                    return self._send(200, {"networks": []})
                self._send(404, {"error": "no such thing"})

        return H

@pytest.fixture
def cloud():
    spy = Cloud()
    server = HTTPServer(("127.0.0.1", 0), spy.handler())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    spy.port = server.server_port
    yield spy
    server.shutdown()

def reader(spy):
    base = f"http://127.0.0.1:{spy.port}"
    return openstack.http_reader(
        openstack.Cloud(keystone=base, neutron=base, nova=base, project="fsl",
                        user="fsl", ssh_user="fsl", ssh_key="/keys/fsl"),
        password="secret",
    )

def test_it_authenticates_before_it_asks_anything(cloud):
    reader(cloud)(f"GET http://127.0.0.1:{cloud.port}/v2.0/networks")

    assert cloud.tokens == 1
    path, headers = cloud.seen[0]
    assert headers.get("X-Auth-Token") == "tok1", headers

def test_it_says_which_compute_microversion_it_was_written_against(cloud):
    reader(cloud)(f"GET http://127.0.0.1:{cloud.port}/servers/detail")

    _, headers = cloud.seen[0]
    assert headers.get("X-OpenStack-Nova-API-Version") == openstack.NOVA_MICROVERSION, (
        "Nova's own guide says that with no microversion header it acts as if "
        "the minimum was specified, so the adapter would silently get 2.1 and "
        "a field added later would simply not be there"
    )

def test_a_token_that_expired_is_replaced_once_and_the_call_retried(cloud):
    ask = reader(cloud)
    ask(f"GET http://127.0.0.1:{cloud.port}/v2.0/networks")
    cloud.expire_after = 0

    answered = ask(f"GET http://127.0.0.1:{cloud.port}/v2.0/networks")

    assert answered == {"networks": []}
    assert cloud.tokens == 2, (
        "a Keystone token has a lifetime and a console left open outstays it. "
        "Without a retry the range simply becomes unreadable after an hour"
    )

def test_a_401_that_survives_a_fresh_token_is_reported_not_looped(cloud):
    ask = reader(cloud)
    cloud.always_401 = True

    with pytest.raises(RangeUnavailable, match="401"):
        ask(f"GET http://127.0.0.1:{cloud.port}/v2.0/networks")

def test_anything_else_the_cloud_refuses_is_named(cloud):
    with pytest.raises(RangeUnavailable, match="404"):
        reader(cloud)(f"GET http://127.0.0.1:{cloud.port}/nope")

def test_a_cloud_that_is_not_there_is_unavailable_not_a_crash():
    ask = openstack.http_reader(
        openstack.Cloud(keystone="http://127.0.0.1:1", neutron="http://127.0.0.1:1",
                        nova="http://127.0.0.1:1", project="fsl",
                        user="fsl", ssh_user="fsl", ssh_key="/k"),
        password="secret",
    )

    with pytest.raises(RangeUnavailable):
        ask("GET http://127.0.0.1:1/v2.0/networks")

def test_an_adapter_with_nowhere_else_to_look_names_the_cloud_it_could_not_reach():
    from range import declared

    far = "http://127.0.0.1:1"
    cloudspec = openstack.Cloud(keystone=far, neutron=far, nova=far, project="fsl",
                                user="fsl", ssh_user="fsl", ssh_key="/k")
    adapter = openstack.OpenStack(
        declared.read(), cloudspec, get=openstack.http_reader(cloudspec, "secret")
    )

    with pytest.raises(RangeUnavailable, match=f"could not reach {far}"):
        adapter.describe()


REAL_SHAPES = {
    "networks": [
        {"id": "net-edge", "name": "range1-edge-v4", "tags": ["fsl.segment.id=edge"],
         "admin_state_up": True, "status": "ACTIVE", "shared": False,
         "project_id": "fsl", "subnets": ["sub-edge"]},
    ],
    "subnets": [{"cidr": "5.188.10.0/24", "gateway_ip": "5.188.10.1",
                 "id": "sub-edge", "network_id": "net-edge", "ip_version": 4}],
    "servers": [
        {"name": "fsl-waf", "id": "srv-waf", "status": "ACTIVE",
         "addresses": {"range1-edge-v4": [
             {"addr": "5.188.10.4", "OS-EXT-IPS-MAC:mac_addr": "00:0c:29:0d:11:74",
              "OS-EXT-IPS:type": "fixed", "version": 4}]}},
        {"name": "fsl-suricata", "id": "srv-ids", "status": "ACTIVE",
         "addresses": {"range1-edge-v4": [
             {"addr": "5.188.10.9", "OS-EXT-IPS:type": "fixed", "version": 4}]}},
    ],
}

def test_describe_runs_end_to_end_over_http_against_reference_shapes(cloud):
    from range import declared
    from range.ports import Segment

    class H(cloud.handler()):
        def do_GET(self):
            cloud.seen.append((self.path, dict(self.headers)))
            for key in ("subnets", "servers", "networks"):
                if key in self.path:
                    return self._send(200, {key: REAL_SHAPES[key]})
            self._send(404, {"error": "no"})

    import threading
    from http.server import HTTPServer

    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        one = declared.read()
        only_edge = type(one)(
            segments=tuple(s for s in one.segments if s.id == "edge"),
            roles=one.roles, watches=one.watches, default_origin=one.default_origin,
        )
        cloudspec = openstack.Cloud(keystone=base, neutron=base, nova=base,
                                    project="fsl", user="fsl", ssh_user="fsl", ssh_key="/k")
        shape = openstack.OpenStack(
            only_edge, cloudspec, get=openstack.http_reader(cloudspec, "secret")
        ).describe()
    finally:
        server.shutdown()

    edge = shape.segments[0]
    assert (edge.id, edge.subnet, edge.gateway) == ("edge", "5.188.10.0/24", "5.188.10.1")
    assert [(n.name, n.address) for n in edge.nodes] == [
        ("fsl-suricata", "5.188.10.9"), ("fsl-waf", "5.188.10.4"),
    ]
    assert [(s.name, s.watches) for s in shape.sensors] == [
        ("fsl-suricata", "fsl-waf")
    ]


CATALOG = {
    "token": {
        "expires_at": "2015-11-07T02:58:43.578887Z",
        "catalog": [
            {"type": "identity", "name": "keystone", "endpoints": [
                {"interface": "public", "region_id": "RegionOne",
                 "url": "http://example.com/identity"}]},
            {"type": "network", "name": "neutron", "endpoints": [
                {"interface": "admin", "region_id": "RegionOne",
                 "url": "http://admin.example.com:9696"},
                {"interface": "public", "region_id": "RegionTwo",
                 "url": "http://elsewhere.example.com:9696"},
                {"interface": "public", "region_id": "RegionOne",
                 "url": "http://example.com:9696"}]},
            {"type": "compute", "name": "nova", "endpoints": [
                {"interface": "admin", "region_id": "RegionOne",
                 "url": "http://admin.example.com/compute/v2.1"},
                {"interface": "public", "region_id": "RegionOne",
                 "url": "http://example.com/compute/v2.1"}]},
        ],
    }
}

class Catalogued(Cloud):
    def handler(self):
        spy = self
        base = super().handler()

        class H(base):
            def do_POST(self):
                self._login()
                spy.tokens += 1
                self._send(201, CATALOG, {"X-Subject-Token": f"tok{spy.tokens}"})

        return H

@pytest.fixture
def keystone():
    import threading
    from http.server import HTTPServer

    spy = Catalogued()
    server = HTTPServer(("127.0.0.1", 0), spy.handler())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    spy.port = server.server_port
    yield spy
    server.shutdown()

def test_the_endpoints_come_from_the_token_not_from_configuration(keystone):
    found = openstack.discover(
        keystone=f"http://127.0.0.1:{keystone.port}",
        user="fsl", password="secret", project="fsl",
        ssh_user="fsl", ssh_key="/keys/fsl",
    )

    assert found.neutron == "http://example.com:9696"
    assert found.nova == "http://example.com/compute/v2.1"

def test_it_takes_the_interface_and_region_it_was_asked_for(keystone):
    found = openstack.discover(
        keystone=f"http://127.0.0.1:{keystone.port}",
        user="fsl", password="secret", project="fsl",
        ssh_user="fsl", ssh_key="/keys/fsl",
        interface="admin",
    )

    assert (found.neutron, found.nova) == (
        "http://admin.example.com:9696",
        "http://admin.example.com/compute/v2.1",
    ), (
        "a catalogue carries public, admin and internal endpoints for the same "
        "service, and a platform on a management network wants a different one "
        "than a browser does"
    )

def test_a_service_the_catalogue_does_not_carry_is_named(keystone):
    with pytest.raises(RangeUnavailable) as raised:
        openstack.discover(
            keystone=f"http://127.0.0.1:{keystone.port}",
            user="fsl", password="secret", project="fsl",
            ssh_user="fsl", ssh_key="/k", region="RegionThree",
        )

    assert "network" in str(raised.value) and "RegionThree" in str(raised.value), (
        f"the deployment has to be told which service is missing from which "
        f"region, not handed an empty URL: {raised.value}"
    )

def test_the_keystone_url_is_the_only_address_a_deployment_must_know(keystone):
    import inspect

    signature = inspect.signature(openstack.discover)

    assert "neutron" not in signature.parameters
    assert "nova" not in signature.parameters


def test_a_token_about_to_expire_is_renewed_before_the_call(keystone):
    from datetime import datetime, timedelta, timezone

    soon = (datetime.now(timezone.utc) + timedelta(seconds=5)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    CATALOG["token"]["expires_at"] = soon
    try:
        base = f"http://127.0.0.1:{keystone.port}"
        ask = openstack.http_reader(
            openstack.Cloud(keystone=base, neutron=base, nova=base,
                            project="fsl", user="fsl", ssh_user="fsl", ssh_key="/k"),
            password="secret",
        )
        ask(f"{base}/v2.0/networks")
        ask(f"{base}/v2.0/networks")
    finally:
        CATALOG["token"]["expires_at"] = "2015-11-07T02:58:43.578887Z"

    assert keystone.tokens == 2, (
        "the token said it expires in five seconds and the adapter kept using "
        "it, so the range goes unreadable mid-session and only a 401 tells it"
    )

def test_a_token_with_life_left_is_not_thrown_away(keystone):
    from datetime import datetime, timedelta, timezone

    later = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    CATALOG["token"]["expires_at"] = later
    try:
        base = f"http://127.0.0.1:{keystone.port}"
        ask = openstack.http_reader(
            openstack.Cloud(keystone=base, neutron=base, nova=base,
                            project="fsl", user="fsl", ssh_user="fsl", ssh_key="/k"),
            password="secret",
        )
        for _ in range(4):
            ask(f"{base}/v2.0/networks")
    finally:
        CATALOG["token"]["expires_at"] = "2015-11-07T02:58:43.578887Z"

    assert keystone.tokens == 1, (
        f"{keystone.tokens} tokens for four calls - re-authenticating on every "
        f"request puts a Keystone round trip in front of every read"
    )

def test_a_token_with_no_expiry_is_used_until_it_is_refused(keystone):
    CATALOG["token"].pop("expires_at", None)
    try:
        base = f"http://127.0.0.1:{keystone.port}"
        ask = openstack.http_reader(
            openstack.Cloud(keystone=base, neutron=base, nova=base,
                            project="fsl", user="fsl", ssh_user="fsl", ssh_key="/k"),
            password="secret",
        )
        ask(f"{base}/v2.0/networks")
        ask(f"{base}/v2.0/networks")
    finally:
        CATALOG["token"]["expires_at"] = "2015-11-07T02:58:43.578887Z"

    assert keystone.tokens == 1, (
        "a response without expires_at made the adapter re-authenticate every "
        "time rather than fall back to the 401 it already handles"
    )

def test_the_cloud_is_read_as_the_keystone_user_not_the_ssh_login(cloud):
    base = f"http://127.0.0.1:{cloud.port}"
    ask = openstack.http_reader(
        openstack.Cloud(keystone=base, neutron=base, nova=base, project="fsl",
                        user="range-operator", ssh_user="debian", ssh_key="/k"),
        password="secret",
    )

    ask(f"{base}/v2.0/networks")

    assert cloud.logins == ["range-operator"], (
        f"the account a platform signs in to Keystone with and the login on "
        f"an instance's image are two different people: {cloud.logins}"
    )

def test_discovery_remembers_who_it_signed_in_as(keystone):
    found = openstack.discover(
        keystone=f"http://127.0.0.1:{keystone.port}",
        user="range-operator", password="secret", project="fsl",
        ssh_user="debian", ssh_key="/k",
    )

    assert (found.user, found.ssh_user) == ("range-operator", "debian")

def test_a_refused_sign_in_is_named_rather_than_blamed_on_a_missing_header(cloud):
    cloud.refuse_logins = True

    with pytest.raises(RangeUnavailable) as raised:
        reader(cloud)(f"http://127.0.0.1:{cloud.port}/v2.0/networks")

    assert "401" in str(raised.value) and "disabled" in str(raised.value), (
        f"Keystone said why it refused and the operator was told only that "
        f"no token header came back: {raised.value}"
    )

def test_discovery_carries_the_deployment_s_ssh_config(keystone):
    found = openstack.discover(
        keystone=f"http://127.0.0.1:{keystone.port}",
        user="fsl", password="secret", project="fsl",
        ssh_user="debian", ssh_key="/k", ssh_config="/etc/fsl/ssh_config",
    )

    assert found.ssh_config == "/etc/fsl/ssh_config", (
        "a platform that reaches the range through a bastion says so in an "
        "ssh config, and discovery is the only way a deployment builds a Cloud"
    )
