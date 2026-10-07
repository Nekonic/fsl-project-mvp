from pf_prime import mgmt_address, primed_line
from range.ports import Node, Segment

def _segments():
    return (
        Segment(id="estate", name="estate", nodes=(Node(name="fsl-pfsense", address="10.30.0.1"),)),
        Segment(id="mgmt", name="mgmt", nodes=(
            Node(name="fsl-waf", address="10.31.0.9"),
            Node(name="fsl-pfsense", address="10.31.0.158"),
        )),
    )

def test_mgmt_address_finds_the_pfsense_node_on_the_mgmt_segment():
    assert mgmt_address(_segments()) == "10.31.0.158"

def test_mgmt_address_is_none_when_the_host_is_absent():
    only_waf = (Segment(id="mgmt", name="mgmt", nodes=(Node(name="fsl-waf", address="10.31.0.9"),)),)
    assert mgmt_address(only_waf) is None

def test_the_primed_line_names_the_upstream_host_and_session():
    assert primed_line("10.31.0.158", "abc123") == "http://10.31.0.158:80 10.31.0.158 abc123"


import pf_prime


class _Body:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body


def test_authenticated_is_true_when_the_dashboard_comes_back(monkeypatch):
    monkeypatch.setattr(
        "pf_prime.urllib.request.urlopen",
        lambda request, timeout=10: _Body(b"<html>System / Dashboard</html>"),
    )
    assert pf_prime.authenticated("10.31.0.158", "sess") is True


def test_authenticated_is_false_when_the_login_form_comes_back(monkeypatch):
    monkeypatch.setattr(
        "pf_prime.urllib.request.urlopen",
        lambda request, timeout=10: _Body(b'<input name="usernamefld">'),
    )
    assert pf_prime.authenticated("10.31.0.158", "sess") is False


def test_authenticated_is_false_when_the_request_raises(monkeypatch):
    def boom(request, timeout=10):
        raise OSError("connection refused")

    monkeypatch.setattr("pf_prime.urllib.request.urlopen", boom)
    assert pf_prime.authenticated("10.31.0.158", "sess") is False


def _cookie(name, value):
    from http.cookiejar import Cookie

    return Cookie(
        version=0, name=name, value=value, port=None, port_specified=False,
        domain="", domain_specified=False, domain_initial_dot=False,
        path="/", path_specified=True, secure=False, expires=None, discard=True,
        comment=None, comment_url=None, rest={}, rfc2109=False,
    )


def test_login_posts_the_csrf_token_and_returns_the_session(monkeypatch):
    posted = {}

    class FakeOpener:
        def __init__(self, jar):
            self.jar = jar
            self.addheaders = []

        def open(self, request, timeout=10):
            url = request if isinstance(request, str) else request.full_url
            if url.endswith("/index.php"):
                posted["data"] = request.data
                self.jar.set_cookie(_cookie("PHPSESSID", "sess-xyz"))
                return _Body(b"ok")
            return _Body(b'<input type="hidden" name="__csrf_magic" value="sid:ABC123;ip:deadbeef">')

    monkeypatch.setattr(
        "pf_prime.urllib.request.build_opener",
        lambda *handlers: FakeOpener(handlers[0].cookiejar),
    )

    session = pf_prime.login("10.31.0.158")

    assert session == "sess-xyz"
    assert b"sid%3AABC123" in posted["data"], (
        "the extracted __csrf_magic token must be posted with the login form"
    )
