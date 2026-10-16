import os
import pathlib
import pwd
import shutil
import signal
import socket
import subprocess
import time
from dataclasses import replace

import pytest

from range import declared, openstack
from range.ports import RangeUnavailable, Segment

SSHD = shutil.which("sshd") or "/usr/sbin/sshd"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def keygen(path: pathlib.Path) -> pathlib.Path:
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)],
        check=True,
    )
    return path


def start_sshd(home: pathlib.Path, port: int, host_key: pathlib.Path):
    config = home / f"sshd_config-{host_key.name}"
    config.write_text(
        f"Port {port}\n"
        "ListenAddress 127.0.0.1\n"
        f"HostKey {host_key}\n"
        f"AuthorizedKeysFile {home / 'authorized_keys'}\n"
        "PasswordAuthentication no\n"
        "KbdInteractiveAuthentication no\n"
        "UsePAM no\n"
        "StrictModes no\n"
        "PermitUserRC no\n"
        f"SetEnv ZDOTDIR={home}\n"
        f"PidFile {home / 'sshd.pid'}\n"
    )
    said = home / f"sshd-{host_key.name}.log"
    daemon = subprocess.Popen(
        [SSHD, "-D", "-e", "-f", str(config)],
        stdout=subprocess.DEVNULL, stderr=said.open("w"),
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and daemon.poll() is None:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return daemon
        time.sleep(0.05)
    daemon.kill()
    daemon.wait()
    pytest.fail(f"{SSHD} did not listen on {port}: {said.read_text()}")


def descendants(pid: int) -> list[int]:
    found = []
    listed = subprocess.run(
        ["pgrep", "-P", str(pid)], capture_output=True, text=True
    ).stdout.split()
    for child in map(int, listed):
        found += [child, *descendants(child)]
    return found


@pytest.fixture
def host(tmp_path):
    if not os.access(SSHD, os.X_OK):
        pytest.fail(
            f"these tests run the adapter against a real sshd and there is "
            f"none at {SSHD}"
        )
    client = keygen(tmp_path / "client")
    (tmp_path / "authorized_keys").write_text(
        (tmp_path / "client.pub").read_text()
    )
    port = free_port()
    daemon = start_sshd(tmp_path, port, keygen(tmp_path / "host-a"))
    (tmp_path / "ssh_config").write_text(
        f"Port {port}\n"
        f"UserKnownHostsFile {tmp_path / 'known_hosts'}\n"
    )
    state = {"home": tmp_path, "port": port, "key": client, "daemon": daemon}
    yield state
    for pid in descendants(state["daemon"].pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    state["daemon"].kill()
    state["daemon"].wait()


FIRST_BOOT = "2026-09-23T10:00:00.000000"


def adapter(
    host, server_id="kali-1", launched_at=FIRST_BOOT, **cloud
) -> openstack.OpenStack:
    declaration = replace(
        declared.read(), origins=(), segments=(Segment(id="mgmt", name="Management"),)
    )
    standing = declaration.segments[0].id
    networks = {
        "networks": [
            {
                "id": f"net-{segment.id}",
                "name": f"net-{segment.id}",
                "tags": [f"{openstack.SEGMENT_TAG}={segment.id}"],
            }
            for segment in declaration.segments
        ]
    }
    servers = {
        "servers": [
            {
                "id": server_id,
                "name": declaration.roles["attacker"],
                openstack.LAUNCHED: launched_at,
                "addresses": {
                    f"net-{standing}": [
                        {"addr": "127.0.0.1", openstack.FIXED: "fixed"}
                    ]
                },
            }
        ]
    }

    def get(call):
        if "/v2.0/networks" in call:
            return networks
        if "/v2.0/subnets" in call:
            return {"subnets": []}
        return servers

    reaching = openstack.Cloud(**{
        "keystone": "http://keystone.invalid",
        "neutron": "http://neutron.invalid",
        "nova": "http://nova.invalid",
        "project": "fsl",
        "user": "fsl",
        "ssh_user": pwd.getpwuid(os.getuid()).pw_name,
        "ssh_key": str(host["key"]),
        "ssh_config": str(host["home"] / "ssh_config"),
        **cloud,
    })
    return openstack.OpenStack(declaration, reaching, get=get)


def attacker(host):
    return adapter(host).runner("attacker")


def test_an_argument_reaches_the_host_as_the_argument_it_was(host):
    ran = attacker(host)(["printf", "%s\\n", "a b", "c;d", "$HOME"])

    assert ran.output == "a b\nc;d\n$HOME\n", (
        "ssh appends the arguments to the command separated by spaces and "
        "hands the result to the remote shell, so without quoting 'a b' "
        "arrives as two arguments and 'c;d' runs d. The docker adapter "
        f"passes an argv through exactly and so must this one: {ran.output!r}"
    )


def test_an_argument_that_looks_like_an_option_stays_on_the_host(host):
    landed = host["home"] / "ran-on-the-platform"

    ran = attacker(host)(["-oProxyCommand=/usr/bin/touch", str(landed)])

    assert not landed.exists(), (
        "ssh reads options after the destination too, so a command starting "
        "with -o was taken as ProxyCommand and run on the platform itself"
    )
    assert ran.exit_code == 127, (
        f"on the host it is a command that does not exist, the way docker "
        f"exec would report it - not options for the shell that runs it: {ran}"
    )


@pytest.mark.parametrize("script, exit_code, output", [
    ("exit 3", 3, ""),
    ("echo tried >&2; exit 255", 255, "tried\n"),
    ("kill -9 $$", 128 + signal.SIGKILL, None),
])
def test_the_exit_code_is_the_command_s_as_docker_exec_reports_it(host, script, exit_code, output):
    ran = attacker(host)(["sh", "-c", script])

    assert (ran.exit_code, ran.output if output is not None else None) == (exit_code, output), (
        "ssh exits 255 both when it fails and when the command does; sqlmap "
        f"exits 255 on any unhandled exception, a tool that ran: {ran}"
    )


def test_a_host_met_for_the_first_time_takes_the_input_and_returns_only_the_command_s_output(host):
    ran = attacker(host)(["sh", "-c", "cat; printf 'a\\377b'"], stdin="alert http any\n")

    assert (ran.exit_code, ran.output) == (0, "alert http any\na\ufffdb"), (
        "every instance on a fresh cloud has a host key nobody has seen, what ssh "
        f"says about itself is not output, and bytes that are not UTF-8 must not raise: {ran}"
    )


def another_key_answers(host, name="host-b"):
    host["daemon"].kill()
    host["daemon"].wait()
    host["daemon"] = start_sshd(host["home"], host["port"], keygen(host["home"] / name))


def test_another_machine_at_an_instance_s_address_is_refused(host):
    assert attacker(host)(["true"]).exit_code == 0

    another_key_answers(host)

    with pytest.raises(RangeUnavailable, match="Host key verification failed"):
        adapter(host).runner("attacker")(["true"])


@pytest.mark.parametrize("generation", [
    dict(launched_at="2026-09-23T11:30:00.000000"),
    dict(server_id="kali-2"),
])
def test_a_rebuilt_instance_or_a_new_one_on_an_old_address_is_reached_again(host, generation):
    assert attacker(host)(["true"]).exit_code == 0

    another_key_answers(host)

    assert adapter(host, **generation).runner("attacker")(["true"]).exit_code == 0, (
        "a rebuild recreates the root disk and cloud-init makes new host keys, "
        "so every rebuild on a range that is rebuilt constantly locked the "
        "platform out of that role until someone edited known_hosts by hand"
    )


def test_a_command_that_outlives_its_timeout_is_named_as_such(host):
    with pytest.raises(RangeUnavailable, match="did not finish within 1s"):
        attacker(host)(["sleep", "5"], timeout=1)
