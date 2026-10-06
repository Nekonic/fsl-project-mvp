from unittest.mock import patch

from range.ports import RangeUnavailable

URL = "/api/range/console/fsl-pfsense/"

class CloudAdapter:
    def __init__(self, url="http://nova/vnc_lite.html?token=1", fail=None):
        self.url = url
        self.fail = fail

    def console(self, host):
        if self.fail is not None:
            raise self.fail
        return self.url

class ComposeAdapter:
    pass

def test_the_console_url_comes_from_the_cloud(client):
    with patch("api.views.substrate", lambda: CloudAdapter()):
        answer = client.get(URL)

    assert answer.status_code == 200
    assert answer.json() == {"url": "http://nova/vnc_lite.html?token=1"}

def test_the_compose_range_has_no_console_to_frame(client):
    with patch("api.views.substrate", lambda: ComposeAdapter()):
        answer = client.get(URL)

    assert answer.status_code == 409, answer.content

def test_an_unbooted_host_reads_as_unavailable(client):
    with patch("api.views.substrate", lambda: CloudAdapter(fail=RangeUnavailable("no server fills it"))):
        answer = client.get(URL)

    assert answer.status_code == 503, answer.content

def test_the_console_is_only_a_get(client):
    assert client.post_json(URL).status_code == 405
