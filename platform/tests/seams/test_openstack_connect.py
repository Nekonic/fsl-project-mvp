import dataclasses
import ipaddress
import json
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from cr import config as config_module
from cr.config import OpenStackConfig, RangeConfig
from range import declaration, openstack, substrate
from range.runner import RangeUnavailable

ROOT = pathlib.Path(__file__).resolve().parents[3]


class Cloud:
    def __init__(self):
        self.tokens = 0
        self.port = 0
        self.services = ""
        self.gone = set()

    def handler(self):
        cloud = self
        declared = declaration.read()
        origins = {o.id: o for o in declared.origins}
        carriers = list(dict.fromkeys(
            origins[s.id].segment if s.id in origins else s.id for s in declared.segments
        ))
        numbered = {f"net-{c}": n for n, c in enumerate(carriers)}

        def allocated(network_id):
            carrier = network_id.removeprefix("net-")
            if carrier in {o.segment for o in origins.values()}:
                return [
                    {"cidr": o.subnet, "gateway_ip": str(next(ipaddress.ip_network(o.subnet).hosts()))}
                    for o in origins.values() if o.segment == carrier
                ]
            n = numbered[network_id]
            return [{"cidr": f"198.51.{n}.0/24", "gateway_ip": f"198.51.{n}.1"}]

        def standing(role, host):
            return {
                "id": role, "name": declared.roles[role],
                "addresses": {
                    f"range-{origin.segment}": [
                        {
                            "addr": str(list(ipaddress.ip_network(o.subnet).hosts())[host - 1]),
                            openstack.FIXED: "fixed",
                        }
                        for o in origins.values()
                    ]
                    for origin in list(origins.values())[:1]
                },
            }

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
                self.rfile.read(int(self.headers["Content-Length"]))
                cloud.tokens += 1
                here = cloud.services or f"http://127.0.0.1:{cloud.port}"
                self._send(201, {"token": {"catalog": [
                    {"type": "network", "endpoints": [{
                        "interface": "public", "region_id": "RegionOne", "url": here,
                    }]},
                    {"type": "compute", "endpoints": [{
                        "interface": "public", "region_id": "RegionOne", "url": here,
                    }]},
                    {"type": "image", "endpoints": [{
                        "interface": "public", "region_id": "RegionOne", "url": here,
                    }]},
                    {"type": "orchestration", "endpoints": [{
                        "interface": "public", "region_id": "RegionOne", "url": here,
                    }]},
                ]}}, {"X-Subject-Token": f"tok{cloud.tokens}"})

            def do_GET(self):
                if self.server.server_port in cloud.gone:
                    return self._send(404, {"error": self.path})
                if "/v2.0/networks" in self.path:
                    return self._send(200, {"networks": [
                        {"id": f"net-{c}", "name": f"range-{c}",
                         "tags": [f"{openstack.SEGMENT_TAG}={c}"]}
                        for c in carriers
                    ]})
                if "/v2.0/subnets" in self.path:
                    return self._send(200, {"subnets": allocated(self.path.rsplit("=", 1)[1])})
                if "/servers/detail" in self.path:
                    return self._send(200, {"servers": [
                        standing("proxy", 5), standing("gateway", 4),
                    ]})
                self._send(404, {"error": self.path})

        return H


@pytest.fixture
def cloud():
    fake = Cloud()
    server = HTTPServer(("127.0.0.1", 0), fake.handler())
    fake.port = server.server_port
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    openstack.forget()
    yield fake
    openstack.forget()
    server.shutdown()
    server.server_close()


def options(cloud, **overrides):
    return OpenStackConfig(**{
        "keystone": f"http://127.0.0.1:{cloud.port}",
        "user": "range-operator",
        "password": "secret",
        "project": "cr",
        "ssh_user": "debian",
        "ssh_key": "/keys/cr",
        "region": "RegionOne",
        "interface": "public",
        "domain": "default",
        "source": str(ROOT),
        "subnets": "mgmt=10.31.0.0/24",
        **overrides,
    })


def serving(cloud) -> HTTPServer:
    server = HTTPServer(("127.0.0.1", 0), cloud.handler())
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    cloud.services = f"http://127.0.0.1:{server.server_port}"
    return server


@pytest.mark.parametrize("left_behind", ["closed", "answering 404"])
def test_services_the_cloud_moved_are_found_again(cloud, left_behind):
    before = serving(cloud)
    try:
        openstack.connect(options(cloud), declaration.read()).describe()
        after = serving(cloud)
        if left_behind == "closed":
            before.shutdown()
            before.server_close()
        else:
            cloud.gone.add(before.server_port)
        try:
            shape = openstack.connect(options(cloud), declaration.read()).describe()
        finally:
            after.shutdown()
            after.server_close()
    finally:
        before.shutdown()
        before.server_close()

    assert [s.id for s in shape.segments] == [s.id for s in declaration.read().segments], (
        "Keystone listed the network and compute services somewhere new and "
        "the platform went on asking where the first catalogue said they "
        "were, until it was restarted"
    )


def test_the_substrate_is_built_from_the_range_config_it_is_handed(cloud):
    serving(cloud)
    config = RangeConfig(source=str(ROOT), declaration=str(ROOT / "platform/range/declaration.yaml"),
                         openstack=options(cloud))

    adapter = substrate.substrate(config)

    assert isinstance(adapter, openstack.OpenStack)
    assert {s.id for s in adapter.describe().segments} == {s.id for s in declaration.read().segments}


def test_a_missing_credential_is_named_by_the_variable_that_carries_it(cloud):
    with pytest.raises(RangeUnavailable, match="CR_OPENSTACK_KEYSTONE"):
        openstack.connect(options(cloud, keystone=""), declaration.read())


def test_the_config_hands_the_openstack_substrate_its_credentials_from_the_environment(tmp_path):
    secret = tmp_path / "password"
    secret.write_text("s3cret\n")

    built = config_module.build({"CR_OPENSTACK_KEYSTONE": "https://keystone.example:5000",
                                 "CR_OPENSTACK_PASSWORD_FILE": str(secret)}, ROOT)

    assert built.range.substrate == "range.openstack.connect"
    assert built.range.openstack.keystone == "https://keystone.example:5000"
    assert built.range.openstack.password == "s3cret"
    assert "s3cret" not in repr(built.range.openstack)
    assert set(config_module.OPENSTACK_VARIABLES) <= {f.name for f in dataclasses.fields(OpenStackConfig)}
