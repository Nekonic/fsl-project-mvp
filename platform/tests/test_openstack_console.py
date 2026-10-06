import pytest

from range import slot
from range.ports import RangeUnavailable
from tests.test_openstack_slot import adapter

URL = "http://nova/vnc_lite.html?token=abc123"

class Fake:
    def __init__(self, servers, url=URL):
        self.servers = servers
        self.url = url
        self.calls = []

    def __call__(self, call, body=None):
        verb, _, path = call.partition(" ")
        self.calls.append((verb, path, body))
        if verb == "GET" and "servers/detail" in path:
            return {"servers": self.servers}
        if verb == "POST" and path.endswith("/action"):
            assert "os-getVNCConsole" in (body or {}), body
            return {"console": {"type": "novnc", "url": self.url}}
        raise AssertionError(call)

def _server(host, status="ACTIVE"):
    return {"id": "srv-1", "status": status, "metadata": {slot.HOST: host}}

def test_the_console_url_is_the_hosts_novnc():
    cloud = Fake([_server("fsl-pfsense")])
    assert adapter(cloud).console("fsl-pfsense") == URL
    actions = [c for c in cloud.calls if c[0] == "POST" and c[1].endswith("/action")]
    assert actions and actions[0][2] == {"os-getVNCConsole": {"type": "novnc"}}

def test_a_host_that_is_not_booted_has_no_console():
    with pytest.raises(RangeUnavailable, match="fsl-pfsense"):
        adapter(Fake([])).console("fsl-pfsense")

def test_a_console_without_a_url_is_unavailable():
    with pytest.raises(RangeUnavailable, match="console url"):
        adapter(Fake([_server("fsl-pfsense")], url="")).console("fsl-pfsense")
