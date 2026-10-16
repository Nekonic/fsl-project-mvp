import pathlib
import re

from tests import composed

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONT = ROOT / "platform/nginx.conf"
ENTRYPOINT = ROOT / "platform/entrypoint.sh"

def location(path):
    text = FRONT.read_text()
    start = text.index(f"location {path} {{")
    return text[start:text.index("}", start)]

def test_the_terminal_has_no_port_of_its_own():
    assert not composed.services()["kali"].get("ports"), (
        "everything a person uses is on the platform's one port"
    )

def test_the_terminal_is_handed_over_only_after_the_platform_agrees():
    terminal = location("/terminal/")

    assert "auth_request" in terminal, (
        "the terminal path would skip the platform's refusal of range addresses"
    )

def test_the_platform_sees_the_client_not_the_front():
    forwarded = re.findall(r"proxy_set_header\s+X-Forwarded-For\s+(\S+);", FRONT.read_text())

    assert forwarded and set(forwarded) == {"$remote_addr"}, (
        f"{forwarded}: appending keeps whatever the client claimed"
    )

def test_waitress_answers_the_front_alone_and_trusts_only_it():
    text = ENTRYPOINT.read_text()

    assert "--listen=127.0.0.1:8001" in text
    assert "--trusted-proxy=127.0.0.1" in text
    assert "--trusted-proxy-headers=x-forwarded-for" in text
    assert "--clear-untrusted-proxy-headers" in text
