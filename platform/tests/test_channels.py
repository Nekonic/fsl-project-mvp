import pathlib
import re

import pytest

import attacker
from range.ports import Ran

class Host:
    def __init__(self, reply="", exit_code=0):
        self.calls = []
        self.reply = reply
        self.exit_code = exit_code

    def __call__(self, argv, stdin=None, timeout=60.0):
        self.calls.append((argv, stdin))
        return Ran(self.exit_code, self.reply)

    @property
    def written(self):
        return [(argv[-1], stdin) for argv, stdin in self.calls if stdin is not None]

def test_the_attacker_channel_does_not_name_the_substrate():
    source = re.sub(r"\w+Challenge\b", "", pathlib.Path(attacker.__file__).read_text())
    assert "docker" not in source.lower()

@pytest.mark.parametrize("write, value, sent, where", [
    (attacker.set_label, "c0ffee", "c0ffee", "active"),
    (attacker.set_label, None, "", "active"),
    (attacker.set_origin, "edge-br", "edge-br", "origin"),
])
def test_the_live_case_and_the_origin_reach_the_proxy_through_the_port(write, value, sent, where):
    proxy = Host()

    write(value, proxy)

    assert proxy.written, "nothing was sent to the proxy"
    path, content = proxy.written[-1]
    assert content == sent, "a cleared case must not label the shell's traffic with the word None"
    assert where in path

@pytest.mark.parametrize("write", [attacker.set_label, attacker.set_origin])
def test_a_write_the_proxy_could_not_make_is_not_a_silent_success(write):
    with pytest.raises(attacker.AttackerUnavailable):
        write("c0ffee", Host(reply="sh: can't create /label/origin: Read-only file system", exit_code=1))
