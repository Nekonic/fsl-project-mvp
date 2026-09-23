import json
import os
import pathlib
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from range import declared, openstack
from range.ports import RangeUnavailable

ROOT = pathlib.Path(__file__).resolve().parents[2]


class Cloud:
    def __init__(self):
        self.tokens = 0
        self.port = 0

    def handler(self):
        cloud = self
        declaration = declared.read()
        numbered = {f"net-{s.id}": n for n, s in enumerate(declaration.segments)}

        def standing(role, host):
            return {
                "id": role, "name": declaration.roles[role],
                "addresses": {
                    f"range-{s.id}": [{
                        "addr": f"198.51.{numbered[f'net-{s.id}']}.{host}",
                        openstack.FIXED: "fixed",
                    }]
                    for s in declaration.segments if s.origin
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
                here = f"http://127.0.0.1:{cloud.port}"
                self._send(201, {"token": {"catalog": [
                    {"type": "network", "endpoints": [{
                        "interface": "public", "region_id": "RegionOne", "url": here,
                    }]},
                    {"type": "compute", "endpoints": [{
                        "interface": "public", "region_id": "RegionOne", "url": here,
                    }]},
                ]}}, {"X-Subject-Token": f"tok{cloud.tokens}"})

            def do_GET(self):
                if "/v2.0/networks" in self.path:
                    return self._send(200, {"networks": [
                        {"id": f"net-{s.id}", "name": f"range-{s.id}",
                         "tags": [f"{openstack.SEGMENT_TAG}={s.id}"]}
                        for s in declaration.segments
                    ]})
                if "/v2.0/subnets" in self.path:
                    n = numbered[self.path.rsplit("=", 1)[1]]
                    return self._send(200, {"subnets": [
                        {"cidr": f"198.51.{n}.0/24", "gateway_ip": f"198.51.{n}.1"}
                    ]})
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
    threading.Thread(target=server.serve_forever, daemon=True).start()
    openstack.forget()
    yield fake
    openstack.forget()
    server.shutdown()


def options(cloud, **overrides):
    return {
        "declared": declared.read(),
        "keystone": f"http://127.0.0.1:{cloud.port}",
        "user": "range-operator",
        "password": "secret",
        "project": "fsl",
        "ssh_user": "debian",
        "ssh_key": "/keys/fsl",
        **overrides,
    }


def test_connecting_reads_the_range_through_the_endpoints_keystone_named(cloud):
    shape = openstack.connect(**options(cloud)).describe()

    assert [s.id for s in shape.segments] == [s.id for s in declared.read().segments]


def test_a_request_does_not_sign_in_again(cloud):
    openstack.connect(**options(cloud)).describe()
    after_one = cloud.tokens

    for _ in range(3):
        openstack.connect(**options(cloud)).describe()

    assert cloud.tokens == after_one, (
        f"range.substrate() builds an adapter per request, and each one signed "
        f"in to Keystone and read its catalogue again: {cloud.tokens - after_one} "
        f"more tokens for three more requests"
    )


def test_a_missing_credential_is_named_by_the_setting_that_supplies_it(cloud):
    with pytest.raises(RangeUnavailable) as raised:
        openstack.connect(**options(cloud, password="", project=""))

    assert "FSL_OPENSTACK_PASSWORD" in str(raised.value)
    assert "FSL_OPENSTACK_PROJECT" in str(raised.value)


def test_the_console_draws_an_openstack_range(cloud, client, settings):
    settings.FSL_SUBSTRATE = "range.openstack.connect"
    settings.FSL_SUBSTRATE_OPTIONS = options(cloud)

    response = client.get("/api/origins/")

    assert response.status_code == 200, response.content[:300]
    assert {o["id"] for o in response.json()["origins"]} == {
        s.id for s in declared.read().segments if s.origin
    }


def test_settings_hand_the_openstack_substrate_its_credentials_from_the_environment():
    read = subprocess.run(
        [sys.executable, "-c",
         "import fsl.settings as s; o = s.FSL_SUBSTRATE_OPTIONS; "
         "print(sorted(o)); print(o['keystone'], o['ssh_config'])"],
        cwd=ROOT / "platform", capture_output=True, text=True,
        env={
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "fsl.settings",
            "FSL_SUBSTRATE": "range.openstack.connect",
            "FSL_OPENSTACK_KEYSTONE": "https://keystone.example:5000",
            "FSL_OPENSTACK_SSH_CONFIG": "/etc/fsl/ssh_config",
        },
    )
    assert read.returncode == 0, read.stderr[-300:]

    keys, values = read.stdout.strip().splitlines()
    assert keys == str(sorted([
        "declared", "keystone", "user", "password", "project", "ssh_user",
        "ssh_key", "ssh_config", "region", "interface",
    ]))
    assert values == "https://keystone.example:5000 /etc/fsl/ssh_config"


def test_every_setting_a_refusal_names_is_one_settings_reads():
    source = (ROOT / "platform/fsl/settings.py").read_text()

    unread = [name for name in openstack.SETTINGS.values() if f'"{name}"' not in source]

    assert not unread, (
        f"a missing credential is reported as {unread}, which nothing reads, "
        f"so the deployment sets it and nothing changes"
    )
