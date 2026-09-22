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

            def do_POST(self):
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
                        ssh_user="fsl", ssh_key="/keys/fsl"),
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
                        ssh_user="fsl", ssh_key="/k"),
        password="secret",
    )

    with pytest.raises(RangeUnavailable):
        ask("GET http://127.0.0.1:1/v2.0/networks")


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
                                    project="fsl", ssh_user="fsl", ssh_key="/k")
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
