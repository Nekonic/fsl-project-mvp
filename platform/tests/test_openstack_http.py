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
        self.written = []
        self.write_answers = []

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

            def _write(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                cloud.written.append((self.command, self.path, body, dict(self.headers)))
                code, answer = cloud.write_answers.pop(0) if cloud.write_answers else (201, body)
                if answer is None:
                    self.send_response(code)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self._send(code, answer)

            def do_PUT(self):
                self._write()

            def do_DELETE(self):
                self._write()

            def do_POST(self):
                if not self.path.startswith("/v3/auth/tokens"):
                    return self._write()
                self._login()
                if cloud.refuse_logins:
                    return self._send(401, {"error": {
                        "code": 401, "title": "Unauthorized",
                        "message": "The account is disabled for user: cr",
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
    server.server_close()

def reader(spy):
    base = f"http://127.0.0.1:{spy.port}"
    return openstack.http_reader(
        openstack.Cloud(keystone=base, neutron=base, nova=base, project="cr",
                        user="cr", ssh_user="cr", ssh_key="/keys/cr"),
        password="secret",
    )

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

    assert cloud.tokens == 2, cloud.tokens

def test_an_adapter_with_nowhere_else_to_look_names_the_cloud_it_could_not_reach():
    from range import declared

    far = "http://127.0.0.1:1"
    cloudspec = openstack.Cloud(keystone=far, neutron=far, nova=far, project="cr",
                                user="cr", ssh_user="cr", ssh_key="/k")
    adapter = openstack.OpenStack(
        declared.read(), cloudspec, get=openstack.http_reader(cloudspec, "secret")
    )

    with pytest.raises(RangeUnavailable, match=f"could not reach {far}"):
        adapter.describe()


REAL_SHAPES = {
    "networks": [
        {"id": "net-mgmt", "name": "cr-mgmt", "tags": ["cr.segment.id=mgmt"],
         "admin_state_up": True, "status": "ACTIVE", "shared": False,
         "project_id": "cr", "subnets": ["sub-mgmt"]},
    ],
    "subnets": [{"cidr": "10.31.0.0/24", "gateway_ip": None,
                 "id": "sub-mgmt", "network_id": "net-mgmt", "ip_version": 4}],
    "servers": [
        {"name": "cr-range", "id": "srv-range", "status": "ACTIVE", "metadata": {"cr_host": "cr-range"},
         "addresses": {"cr-mgmt": [
             {"addr": "10.31.0.40", "OS-EXT-IPS-MAC:mac_addr": "fa:16:3e:0d:11:74",
              "OS-EXT-IPS:type": "fixed", "version": 4}],
             "cr-platform": [{"addr": "10.20.0.31", "OS-EXT-IPS:type": "fixed", "version": 4}]}},
        {"name": "cr-platform", "id": "srv-platform", "status": "ACTIVE", "metadata": {},
         "addresses": {"cr-mgmt": [
             {"addr": "10.31.0.2", "OS-EXT-IPS:type": "fixed", "version": 4}]}},
    ],
}

def test_describe_runs_end_to_end_over_http_against_reference_shapes(cloud):
    from range import declared

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
        only_management = type(one)(
            segments=tuple(s for s in one.segments if s.id == "mgmt"),
            roles=one.roles, watches=one.watches, hosts=one.hosts, compose=one.compose,
        )
        cloudspec = openstack.Cloud(keystone=base, neutron=base, nova=base,
                                    project="cr", user="cr", ssh_user="cr", ssh_key="/k")
        shape = openstack.OpenStack(
            only_management, cloudspec, get=openstack.http_reader(cloudspec, "secret")
        ).describe()
    finally:
        server.shutdown()
        server.server_close()

    management = shape.segments[0]
    assert (management.id, management.subnet, management.gateway) == ("mgmt", "10.31.0.0/24", "")
    assert [(n.name, n.address) for n in management.nodes] == [
        ("cr-platform", "10.31.0.2"), ("cr-range", "10.31.0.40"),
    ]
    assert sorted((s.name, s.watches) for s in shape.sensors) == [
        ("cr-edge", "cr-edge"), ("cr-range", "cr-range")
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
            {"type": "image", "name": "glance", "endpoints": [
                {"interface": "admin", "region_id": "RegionOne",
                 "url": "http://admin.example.com:9292"},
                {"interface": "public", "region_id": "RegionOne",
                 "url": "http://example.com:9292"}]},
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
    server.server_close()

@pytest.mark.parametrize("interface, neutron, nova", [
    ("public", "http://example.com:9696", "http://example.com/compute/v2.1"),
    ("admin", "http://admin.example.com:9696", "http://admin.example.com/compute/v2.1"),
])
def test_the_endpoints_come_from_the_token_not_from_configuration(keystone, interface, neutron, nova):
    found = openstack.discover(
        keystone=f"http://127.0.0.1:{keystone.port}",
        user="range-operator", password="secret", project="cr",
        ssh_user="debian", ssh_key="/keys/cr", interface=interface,
    )

    assert (found.neutron, found.nova) == (neutron, nova)
    assert (found.user, found.ssh_user) == ("range-operator", "debian")

def test_the_cloud_is_read_as_the_keystone_user_not_the_ssh_login(cloud):
    base = f"http://127.0.0.1:{cloud.port}"
    ask = openstack.http_reader(
        openstack.Cloud(keystone=base, neutron=base, nova=base, project="cr",
                        user="range-operator", ssh_user="debian", ssh_key="/k"),
        password="secret",
    )

    ask(f"{base}/v2.0/networks")

    assert cloud.logins == ["range-operator"], (
        f"the account a platform signs in to Keystone with and the login on "
        f"an instance's image are two different people: {cloud.logins}"
    )

def test_a_write_sends_its_verb_its_body_and_the_token_and_reads_the_answer(cloud):
    body = {"network": {"name": "cr-internet"}}
    cloud.write_answers = [(201, {"network": {"id": "net-1", "name": "cr-internet"}})]

    answered = reader(cloud)(f"POST http://127.0.0.1:{cloud.port}/v2.0/networks", body)

    verb, path, sent, headers = cloud.written[0]
    assert (verb, path, sent) == ("POST", "/v2.0/networks", body)
    assert headers.get("X-Auth-Token") == "tok1"
    assert answered == {"network": {"id": "net-1", "name": "cr-internet"}}

def test_a_delete_answered_with_no_body_is_done(cloud):
    cloud.write_answers = [(204, None)]

    assert reader(cloud)(f"DELETE http://127.0.0.1:{cloud.port}/v2.0/subnets/sub-1") == {}
    assert cloud.written[0][:2] == ("DELETE", "/v2.0/subnets/sub-1")

def test_a_refused_write_names_its_address_and_answer(cloud):
    cloud.write_answers = [(409, {"NeutronError": {"message": "overlaps with another subnet"}})]

    with pytest.raises(RangeUnavailable, match="409.*overlaps"):
        reader(cloud)(f"POST http://127.0.0.1:{cloud.port}/v2.0/subnets", {"subnets": []})
