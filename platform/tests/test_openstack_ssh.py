import os
import pathlib
import pwd
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time

import pytest

from range import declared, openstack
from range.ports import RangeUnavailable

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
    declaration = declared.read()
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


def test_the_exit_code_is_the_command_s(host):
    ran = attacker(host)(["sh", "-c", "exit 3"])

    assert ran.exit_code == 3, ran


def test_a_command_that_itself_exits_255_ran(host):
    ran = attacker(host)(["sh", "-c", "echo tried >&2; exit 255"])

    assert (ran.exit_code, ran.output) == (255, "tried\n"), (
        "ssh exits 255 both when it fails and when the command does, so the "
        "exit status alone cannot say which. sqlmap exits 255 on any "
        "unhandled exception; that is a tool that ran, not a range that is "
        f"down: {ran}"
    )


def test_a_command_killed_by_a_signal_ran(host):
    ran = attacker(host)(["sh", "-c", "kill -9 $$"])

    assert ran.exit_code == 128 + signal.SIGKILL, (
        f"docker exec reports a killed command as 137; over ssh it arrived "
        f"as {ran}"
    )


def test_output_that_is_not_utf8_does_not_crash_the_runner(host):
    ran = attacker(host)(["printf", "a\\377b"])

    assert ran.output == "a\ufffdb", ran


def test_a_host_met_for_the_first_time_is_reached(host):
    ran = attacker(host)(["true"])

    assert ran.exit_code == 0, (
        f"every instance on a fresh cloud has a host key nobody has seen, "
        f"and BatchMode alone refuses all of them: {ran.output!r}"
    )
    assert ran.output == "", (
        f"what ssh says about itself is not the command's output: "
        f"{ran.output!r}"
    )


def another_key_answers(host, name="host-b"):
    host["daemon"].kill()
    host["daemon"].wait()
    host["daemon"] = start_sshd(host["home"], host["port"], keygen(host["home"] / name))


def test_another_machine_at_an_instance_s_address_is_refused(host):
    assert attacker(host)(["true"]).exit_code == 0

    another_key_answers(host)

    with pytest.raises(RangeUnavailable) as raised:
        adapter(host).runner("attacker")(["true"])

    assert "REMOTE HOST IDENTIFICATION HAS CHANGED" in str(raised.value)
    assert "Host key verification failed" in str(raised.value), (
        f"Nova says the same instance has stood there since the same boot, "
        f"so a different key is someone else answering at its address: "
        f"{raised.value}"
    )


def test_a_rebuilt_instance_is_reached_again(host):
    assert attacker(host)(["true"]).exit_code == 0

    another_key_answers(host)
    rebuilt = adapter(host, launched_at="2026-09-23T11:30:00.000000")

    assert rebuilt.runner("attacker")(["true"]).exit_code == 0, (
        "a rebuild recreates the root disk and cloud-init makes new host keys, "
        "so every rebuild on a range that is rebuilt constantly locked the "
        "platform out of that role until someone edited known_hosts by hand"
    )


def test_a_new_instance_given_an_old_address_is_reached(host):
    assert attacker(host)(["true"]).exit_code == 0

    another_key_answers(host)
    replaced = adapter(host, server_id="kali-2")

    assert replaced.runner("attacker")(["true"]).exit_code == 0, (
        "Neutron hands a fixed address to the next instance, and that instance "
        "is not an impostor of the last one"
    )


def test_a_reboot_is_not_a_rebuild(host):
    assert attacker(host)(["true"]).exit_code == 0

    another_key_answers(host)

    with pytest.raises(RangeUnavailable):
        adapter(host, launched_at=FIRST_BOOT).runner("attacker")(["true"])


def pinned_by_address(host, key: pathlib.Path, checking="yes"):
    pinned = host["home"] / "pinned"
    pinned.write_text(
        f"[127.0.0.1]:{host['port']} {key.with_suffix('.pub').read_text()}"
    )
    (host["home"] / "ssh_config").write_text(
        f"Port {host['port']}\n"
        f"UserKnownHostsFile {pinned}\n"
        f"StrictHostKeyChecking {checking}\n"
    )


def test_a_deployment_that_pins_its_own_keys_is_not_overruled(host):
    pinned_by_address(host, keygen(host["home"] / "someone-else"))

    with pytest.raises(RangeUnavailable) as raised:
        attacker(host)(["true"])

    assert "REMOTE HOST IDENTIFICATION HAS CHANGED" in str(raised.value), (
        f"the deployment pinned another key at this address, so the host "
        f"answering is not the one it trusts: {raised.value}"
    )


@pytest.mark.parametrize("checking", ["yes", "ask"])
def test_a_key_the_deployment_pinned_by_address_is_accepted(host, checking):
    pinned_by_address(host, host["home"] / "host-a", checking)

    ran = attacker(host)(["true"])

    assert ran.exit_code == 0, (
        f"the deployment pinned this host's own key under its address and "
        f"checks strictly, so its key was looked up under the platform's "
        f"alias instead and every host was refused: {ran}"
    )


def test_a_deployment_s_own_host_key_alias_is_the_one_keys_are_filed_under(host):
    known = host["home"] / "known_hosts"
    (host["home"] / "ssh_config").write_text(
        f"Port {host['port']}\n"
        f"UserKnownHostsFile {known}\n"
        "Match final\n"
        "  HostKeyAlias kali.range\n"
    )

    assert attacker(host)(["true"]).exit_code == 0
    assert known.read_text().startswith("kali.range "), (
        f"a Match final block is read in a second pass, after the platform's "
        f"own alias was already taken, so the deployment's name for this host "
        f"was ignored: {known.read_text()!r}"
    )


@pytest.mark.parametrize("named", [
    "~/deploy/ssh_config",
    "{home}/deploy dir/ssh_config",
    '{home}/the "range" at 100% [${HOME}] back\\slash/ssh_config',
])
def test_a_deployment_config_is_read_whatever_its_path_holds(host, monkeypatch, named):
    monkeypatch.setenv("HOME", str(host["home"]))
    named = named.replace("{home}", str(host["home"]))
    placed = pathlib.Path(named).expanduser()
    placed.parent.mkdir()
    (host["home"] / "ssh_config").rename(placed)

    run = adapter(host, ssh_config=named).runner("attacker")

    assert run(["true"]).exit_code == 0, (
        f"the deployment's ssh config holds the port this host answers on, "
        f"and {named!r} was not the file ssh was told to include"
    )


def test_a_deployment_s_bastion_is_not_given_the_instance_s_key(host, tmp_path):
    bastion_port = free_port()
    bastion = start_sshd(tmp_path, bastion_port, keygen(tmp_path / "bastion"))
    try:
        (host["home"] / "ssh_config").write_text(
            f"UserKnownHostsFile {host['home'] / 'known_hosts'}\n"
            f"Host jump\n"
            f"  HostName 127.0.0.1\n"
            f"  Port {bastion_port}\n"
            f"  User {pwd.getpwuid(os.getuid()).pw_name}\n"
            f"  IdentityFile {host['key']}\n"
            f"  IdentitiesOnly yes\n"
            f"  BatchMode yes\n"
            f"Host 127.0.0.1\n"
            f"  Port {host['port']}\n"
            f"  ProxyJump jump\n"
        )
        run = attacker(host)

        first = run(["true"])
        assert (first.exit_code, first.output) == (0, ""), (
            f"the jump host's own ssh wrote into the command's output: {first}"
        )
        assert run(["true"]).exit_code == 0, (
            "the jump host's key was filed under the instance's alias, so the "
            "second connection took the bastion for an impostor"
        )
    finally:
        for pid in descendants(bastion.pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        bastion.kill()
        bastion.wait()


def test_why_a_bastion_could_not_be_reached_is_named(host):
    closed = free_port()
    (host["home"] / "ssh_config").write_text(
        f"UserKnownHostsFile {host['home'] / 'known_hosts'}\n"
        f"Host jump\n"
        f"  HostName 127.0.0.1\n"
        f"  Port {closed}\n"
        f"Host 127.0.0.1\n"
        f"  Port {host['port']}\n"
        f"  ProxyJump jump\n"
    )

    with pytest.raises(RangeUnavailable) as raised:
        attacker(host)(["true"])

    assert f"port {closed}: Connection refused" in str(raised.value), (
        f"ssh runs the jump host's connection as a second ssh that does not "
        f"write to the first one's log, so its reason was thrown away: "
        f"{raised.value}"
    )


def test_a_refused_login_is_named(host):
    (host["home"] / "authorized_keys").write_text("")

    with pytest.raises(RangeUnavailable, match="Permission denied"):
        attacker(host)(["true"])


def test_input_that_was_given_arrives(host):
    ran = attacker(host)(["cat"], stdin="alert http any\n")

    assert ran.output == "alert http any\n", ran


def test_a_command_given_no_input_reads_none_of_the_platform_s(host):
    read_end, write_end = os.pipe()
    os.write(write_end, b"the platform's own stdin\n")
    os.close(write_end)
    saved = os.dup(0)
    os.dup2(read_end, 0)
    try:
        ran = attacker(host)(["cat"], timeout=10)
    finally:
        os.dup2(saved, 0)
        os.close(saved)
        os.close(read_end)

    assert ran.output == "", (
        f"a command started with no input read whatever the platform's own "
        f"stdin held: {ran.output!r}"
    )


def test_keys_in_an_agent_do_not_crowd_out_the_configured_one(host, monkeypatch):
    socket_path = pathlib.Path(tempfile.mkdtemp(prefix="fsl-agent-")) / "s"
    agent = subprocess.Popen(
        ["ssh-agent", "-D", "-a", str(socket_path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 5
        while not socket_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        monkeypatch.setenv("SSH_AUTH_SOCK", str(socket_path))
        for n in range(6):
            subprocess.run(
                ["ssh-add", "-q", str(keygen(host["home"] / f"unrelated-{n}"))],
                check=True, env=dict(os.environ, SSH_AUTH_SOCK=str(socket_path)),
            )

        ran = attacker(host)(["true"])
    finally:
        agent.kill()
        agent.wait()
        shutil.rmtree(socket_path.parent, ignore_errors=True)

    assert ran.exit_code == 0, (
        "an agent holding six other keys offered all of them first, and sshd "
        "stops listening after MaxAuthTries (default 6)"
    )


def test_a_command_that_outlives_its_timeout_is_named_as_such(host):
    with pytest.raises(RangeUnavailable, match="did not finish within 1s"):
        attacker(host)(["sleep", "5"], timeout=1)


def test_a_connection_lost_mid_command_is_not_a_command_that_ran(
    host, monkeypatch
):
    monkeypatch.setattr(openstack, "SERVER_ALIVE_INTERVAL", 1)
    monkeypatch.setattr(openstack, "SERVER_ALIVE_COUNT_MAX", 1)
    outcome = {}

    def fire():
        try:
            outcome["ran"] = attacker(host)(["sleep", "20"], timeout=15)
        except RangeUnavailable as exc:
            outcome["refused"] = exc

    started = time.monotonic()
    firing = threading.Thread(target=fire)
    firing.start()
    deadline = time.monotonic() + 5
    while not descendants(host["daemon"].pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.5)
    for pid in descendants(host["daemon"].pid):
        os.kill(pid, signal.SIGSTOP)
    firing.join(20)
    waited = time.monotonic() - started

    assert "refused" in outcome, (
        f"a host that stopped answering mid-command was reported as a "
        f"command that ran: {outcome}"
    )
    assert "did not finish within" not in str(outcome["refused"])
    assert waited < 10, (
        f"a silent host held the call for {waited:.0f}s; without keepalives "
        f"ssh waits for the whole timeout, which is 600s for a tool"
    )


def test_a_host_that_never_answers_is_given_up_before_the_tool_s_timeout(
    host, monkeypatch
):
    assert openstack.CONNECT_TIMEOUT < 60, (
        "the connect timeout is longer than the runner's own default, so it "
        "bounds nothing"
    )
    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen()
    host["home"].joinpath("ssh_config").write_text(
        f"Port {silent.getsockname()[1]}\n"
        f"UserKnownHostsFile {host['home'] / 'known_hosts'}\n"
    )
    monkeypatch.setattr(openstack, "CONNECT_TIMEOUT", 1)
    accepted = []
    threading.Thread(
        target=lambda: accepted.append(silent.accept()), daemon=True
    ).start()

    started = time.monotonic()
    try:
        with pytest.raises(RangeUnavailable):
            adapter(host).launcher(declared.read().segments[0].id)(
                declared.read().roles["attacker"], ["true"], timeout=30
            )
    finally:
        silent.close()
        for connection, _ in accepted:
            connection.close()
    waited = time.monotonic() - started

    assert waited < 10, (
        f"reaching the attacker took {waited:.0f}s to fail. The launcher's "
        f"timeout is how long sqlmap may run, not how long a host that "
        f"accepted the connection and said nothing may hold the console"
    )
