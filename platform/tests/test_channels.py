import pathlib
import re

import pytest

import attacker
from range.ports import Ran, RangeUnavailable

class Host:
    def __init__(self, reply="", unreachable=False, exit_code=0):
        self.calls = []
        self.reply = reply
        self.unreachable = unreachable
        self.exit_code = exit_code

    def __call__(self, argv, stdin=None, timeout=60.0):
        if self.unreachable:
            raise RangeUnavailable("that host is not there")
        self.calls.append((argv, stdin))
        return Ran(self.exit_code, self.reply)

    @property
    def written(self):
        return [(argv[-1], stdin) for argv, stdin in self.calls if stdin is not None]

def test_the_attacker_channel_does_not_name_the_substrate():
    source = re.sub(r"\w+Challenge\b", "", pathlib.Path(attacker.__file__).read_text())
    assert "docker" not in source.lower()

def test_telling_the_proxy_which_case_is_live_goes_through_the_port():
    proxy = Host()

    attacker.set_label("c0ffee", proxy)

    assert proxy.written, "the case marker was not sent anywhere"
    where, sent = proxy.written[-1]
    assert sent == "c0ffee"
    assert "active" in where

def test_clearing_the_case_sends_an_empty_marker_not_the_word_none():
    proxy = Host()

    attacker.set_label(None, proxy)

    assert proxy.written[-1][1] == ""

def test_choosing_an_origin_goes_through_the_port():
    proxy = Host()

    attacker.set_origin("edge-br", proxy)

    where, sent = proxy.written[-1]
    assert sent == "edge-br"
    assert "origin" in where

def test_a_proxy_that_cannot_be_reached_is_not_a_silent_success():
    with pytest.raises(RangeUnavailable):
        attacker.set_label("c0ffee", Host(unreachable=True))

@pytest.mark.parametrize("write", [attacker.set_label, attacker.set_origin])
def test_a_write_the_proxy_could_not_make_is_not_a_silent_success(write):
    refused = "sh: can't create /label/origin: Read-only file system"

    with pytest.raises(attacker.AttackerUnavailable) as raised:
        write("c0ffee", Host(reply=refused, exit_code=1))

    assert refused in str(raised.value), (
        "the proxy said why it could not take the write and the platform "
        "dropped the reason"
    )
