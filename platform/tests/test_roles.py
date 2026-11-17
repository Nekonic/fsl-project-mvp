import importlib.util
import json
import re
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

from range import declared, fabric, sandbox
from wargames import WARGAMES

ROOT = Path(__file__).resolve().parents[2]
ROLES = ROOT / "deploy/roles"
SCRIPTS = ("kali/install.sh", "kali/slot-boot", "waf/install.sh", "waf/slot-boot", "infra/install.sh",
           "infra/slot-boot", "infra/suricatasc", "target/install.sh", "target/wargames")
FILEBEAT = ROOT / "deploy/filebeat/filebeat.yml"
DECLARED = declared.read()
YAML_HEADER = "%YAML 1.1\n---\n"
SHA256 = re.compile(r"[0-9a-f]{64}")


def text(role_file: str) -> str:
    return (ROLES / role_file).read_text()


def assigned(role_file: str) -> dict[str, str]:
    return {name: value.strip('"') for name, value in
            re.findall(r'^([A-Z_0-9]+)=("[^"]*"|\S+)$', text(role_file), re.M)}


def definition(wargame: str = "board") -> sandbox.Definition:
    return sandbox.read(ROOT, wargame)


def planned(wargame: str = "board") -> sandbox.Sandbox:
    return sandbox.plan(definition(wargame), 1, DECLARED.origins, DECLARED.default_origin, "10.31.0.2")


def device(name: str, wargame: str = "board") -> sandbox.Device:
    return definition(wargame).devices[name]


def router_address() -> str:
    found = definition()
    [port] = [one for one in found.ports if one.device == found.filling("edge").name and one.lan == "internet"]
    return port.address


def installed_sources(role: str) -> set[str]:
    sources = set()
    for line in text(f"{role}/install.sh").splitlines():
        words = shlex.split(line.strip()) if line.strip().startswith("install ") else []
        if not words or "-d" in words:
            continue
        operands, skipping = [], False
        for word in words[1:]:
            if skipping:
                skipping = False
            elif word in ("-m", "-o", "-g"):
                skipping = True
            elif not word.startswith("-"):
                operands.append(word)
        sources.update(word for word in operands[:-1] if not word.startswith("$") and "/" not in word)
    return sources


def filled(role_file: str, **values) -> str:
    rendered = text(role_file)
    for name, value in values.items():
        rendered = rendered.replace(f"@{name}@", str(value))
    return rendered


def render_module():
    spec = importlib.util.spec_from_file_location("role_render", ROLES / "target/render.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rendered_wargames(tag="abc", mtu=1442) -> dict[str, dict]:
    render = render_module()
    settings = yaml.safe_load(text("target/wargames.yaml"))
    return {wargame: render.rendered(wargame, yaml.safe_load((ROLES / f"target/{wargame}.yaml").read_text()),
                                     settings, tag, mtu)
            for wargame in sorted(WARGAMES)}


def filebeat_slot(hostname: str) -> str:
    pattern = re.search(r"var slot = /(.+?)/\.exec", FILEBEAT.read_text())[1]
    found = re.match(pattern, hostname)
    return found[1] if found else "1"


@pytest.mark.parametrize("script", SCRIPTS)
def test_every_role_script_is_posix_sh_that_parses(script):
    path = ROLES / script

    assert path.read_text().startswith("#!/bin/sh\n")
    assert path.stat().st_mode & 0o111, f"{script} is run by its path, so it is executable"
    assert subprocess.run(["sh", "-n", str(path)], capture_output=True).returncode == 0


@pytest.mark.parametrize("role", ("kali", "waf", "infra", "target"))
def test_each_install_script_stops_at_the_first_failure_and_installs_only_files_of_its_own_directory(role):
    script = text(f"{role}/install.sh")

    assert script.startswith('#!/bin/sh\nset -eu\ncd "$(dirname "$0")"\n'), (
        "the bake runs install.sh from anywhere; the role's files are found beside it"
    )
    for source in installed_sources(role):
        assert (ROLES / role / source).is_file(), f"{role}/install.sh installs {source}, which is not in its directory"


@pytest.mark.parametrize("role", ("kali", "waf", "infra", "target"))
def test_each_image_leaves_cloud_init_to_run_again_for_every_slot_booted_from_it(role):
    script = text(f"{role}/install.sh").rstrip().splitlines()

    assert script[-1] == "sealed_for_snapshot"
    assert "cloud-init clean --logs" in text(f"{role}/install.sh")
    assert ": > /etc/machine-id" in text(f"{role}/install.sh")


@pytest.mark.parametrize("unit", ("kali/slot-boot.service", "waf/slot-boot.service", "infra/slot-boot.service",
                                  "infra/sensor.service", "target/wargames.service"))
def test_the_boot_units_wait_for_the_slot_s_settings_and_do_nothing_on_the_builder(unit):
    written = text(unit)

    assert "ConditionPathExists=/etc/slot.env" in written, "the builder VM has no slot settings"
    assert "WantedBy=multi-user.target" in written


@pytest.mark.parametrize("role", sandbox.ROLES)
def test_every_unit_a_node_waits_on_before_it_reports_ready_is_one_its_image_installs_and_enables(role):
    script = text(f"{role}/install.sh")

    for unit in sandbox.BOOTS[role]:
        if unit == "nginx.service":
            assert "nginx.service" in text("waf/slot-boot.service") and "systemctl enable nginx" in script
            continue
        assert (ROLES / role / unit).is_file(), f"{role} reports ready after {unit}, which it does not carry"
        assert f"systemctl enable {unit}" in script or re.search(rf"systemctl enable [^\n]*\b{unit}\b", script), (
            f"{unit} has to start at boot for {role} to report ready")


@pytest.mark.parametrize("carried, source", [
    ("kali/bashrc", "deploy/kali/bashrc"),
    ("kali/operator-log.sh", "deploy/kali/operator-log.sh"),
    ("kali/set-origin", "deploy/kali/set-origin"),
    ("kali/stamp.py", "deploy/proxy/stamp.py"),
    ("waf/modsecurity.conf", "deploy/waf/modsecurity.conf"),
    ("waf/board.com.conf", "deploy/waf/board.com.conf"),
    ("infra/suricata.yaml", "deploy/suricata/suricata.yaml"),
    ("infra/local.rules", "deploy/suricata/rules/local.rules"),
    ("target/board.yaml", "wargames/board/compose.yaml"),
    ("target/corp.yaml", "wargames/corp/compose.yaml"),
])
def test_a_role_carries_the_file_the_platform_and_its_tests_read_not_a_copy_that_could_drift(carried, source):
    assert (ROLES / carried).resolve() == (ROOT / source).resolve()


def test_kali_installs_the_headless_set_the_tools_the_cases_run_and_sshd():
    named = assigned("kali/install.sh")
    installed = re.search(r"^installed (.+)$", text("kali/install.sh"), re.M)[1].split()
    packages = {word for word in installed if not word.startswith("$")}
    packages |= {package for word in installed if word.startswith("$") for package in named[word[1:]].split()}
    tools = {case["tool"] for path in (ROOT / "redteam/cases").glob("*.yaml")
             for case in yaml.safe_load(path.read_text()) or () if isinstance(case, dict) and case.get("tool")}

    assert {"kali-linux-headless", "iputils-ping", "traceroute", "openssh-server", "sudo"} <= packages
    assert tools and tools <= packages, "every tool a case runs is installed on the attacker"


def test_kali_keeps_the_files_the_platform_reads_and_writes_where_the_container_had_them():
    script = text("kali/install.sh")

    assert "install -m 0644 stamp.py /usr/local/lib/web-proxy.py" in script
    assert "install -m 0644 operator-log.sh /usr/local/lib/shell-hook.sh" in script
    assert "install -m 0755 set-origin /usr/local/sbin/set-origin" in script
    assert "install -d -m 0711 /var/lib/session" in script
    assert "install -m 0600 /dev/null /var/lib/session/active" in script, (
        "the label file stays readable only by root"
    )
    assert "/var/log/commands.log" in script
    assert "'. /usr/local/lib/shell-hook.sh' >> /etc/bash.bashrc" in script
    assert "install -m 0644 bashrc /root/.bashrc" in script
    assert "ln -sf /usr/share/zoneinfo/Asia/Seoul /etc/localtime" in script


def test_kali_s_web_proxy_listens_where_its_shell_sends_web_requests():
    unit = text("kali/web-proxy.service")
    port = assigned("kali/install.sh")["PROXY_PORT"]

    assert f"--listen-port {port} " in unit
    assert "-s /usr/local/lib/web-proxy.py" in unit and "--set block_global=false" in unit
    assert "http://127.0.0.1:%s" in text("kali/install.sh")


def test_kali_resolves_the_sites_to_the_router_s_public_address_and_routes_through_it():
    router = router_address()

    assert router == "121.134.88.42"
    assert assigned("kali/install.sh")["ROUTER"] == router
    assert assigned("kali/slot-boot")["ROUTER"] == router
    assert assigned("infra/slot-boot")["ROUTER"] == router
    assert sorted(device("cr-waf").names) == ["board.com", "corp.com"]
    assert "'%s board.com\\n%s corp.com\\n'" in text("kali/install.sh")
    assert 'ip route replace default via "$ROUTER" dev "$internet" onlink src "$source"' in text("kali/slot-boot")


def test_nothing_kali_installs_that_a_learner_can_list_carries_the_platform_s_name():
    for name in ("install.sh", "slot-boot", "slot-boot.service", "web-proxy.service"):
        assert not re.search(r"\bcr[-_.]", text(f"kali/{name}")), name


def test_the_waf_builds_pinned_versions_each_checked_by_its_sha256():
    built = assigned("waf/install.sh")
    script = text("waf/install.sh")

    assert {name: built[name] for name in ("NGINX", "MODSECURITY", "CONNECTOR", "CRS")} == {
        "NGINX": "1.24.0", "MODSECURITY": "3.0.16", "CONNECTOR": "1.0.4", "CRS": "4.25.1"}
    for name in ("NGINX", "MODSECURITY", "CONNECTOR", "CRS"):
        assert SHA256.fullmatch(built[f"{name}_SHA256"]), name
        assert f"${name}_SHA256" in script, f"{name}'s download is checked against its digest"
    assert built["RELEASES"].startswith("https://github.com/") and built["CRS_RELEASES"].startswith("https://github.com/")


def test_the_waf_ships_the_audit_and_refused_logs_under_the_tags_filebeat_decodes():
    audit = re.search(r"^SecAuditLog (\S+)$", text("waf/modsecurity.conf"), re.M)[1]
    refused = re.search(r"^access_log (\S+) refused", text("waf/board.com.conf"), re.M)[1]
    shipped = dict((tag, path) for path, tag in
                   re.findall(r'File="([^"]+)" Tag="([^"]+)"', text("waf/log-shipper.conf")))
    filebeat = yaml.safe_dump(yaml.safe_load(FILEBEAT.read_text()))

    assert shipped == {"modsecurity": audit, "nginx": refused}
    assert re.findall(r'programname == "([a-z]+)"', text("infra/log-relay.conf")) == ["modsecurity", "nginx"], (
        "the infra relays exactly the WAF's two logs")
    assert all(f"log.syslog.appname: {tag}" in filebeat for tag in shipped)
    assert assigned("waf/install.sh")["AUDIT_LOG"] == audit
    assert assigned("waf/install.sh")["REFUSED_LOG"] == refused


def test_the_waf_ships_to_the_slot_log_server_by_tcp_on_the_port_the_infra_listens_on():
    shipper = filled("waf/log-shipper.conf", log_server="10.40.0.10")

    assert f'Target="10.40.0.10" Port="{sandbox.SHIPPED_PORT}" Protocol="tcp"' in shipper
    assert f'port="{sandbox.SHIPPED_PORT}" ruleset="relayed"' in text("infra/log-relay.conf")
    assert f'tcp dport {sandbox.SHIPPED_PORT} accept' in text("infra/edge.nft")


@pytest.mark.parametrize("wargame", sorted(WARGAMES))
def test_the_waf_validates_its_configuration_and_reloads_as_the_platform_asks(wargame):
    waf = device("cr-waf", wargame)
    script = text("waf/install.sh")

    assert waf.rules == assigned("waf/install.sh")["EXCLUSIONS"].replace("$MODSEC_DIR",
                                                                        assigned("waf/install.sh")["MODSEC_DIR"])
    assert waf.reload.split()[:2] == ["nginx", "-t"] and "nginx -s reload" in waf.reload
    assert '[ -f "$EXCLUSIONS" ] || install -m 664 -g adm /dev/null "$EXCLUSIONS"' in script
    assert "nginx -t\n" in script
    assert "Before=nginx.service" in text("waf/slot-boot.service"), "nginx resolves board and corp-wp when it starts"


def test_the_waf_and_the_target_agree_on_the_names_of_the_wargames_addresses():
    render = render_module()
    boot = text("waf/slot-boot")

    for wargame in sorted(WARGAMES):
        assert f"${render.address_variable(wargame)}" in boot


def test_the_infra_runs_the_sensor_image_pinned_by_its_digest():
    image = assigned("infra/install.sh")["SENSOR_IMAGE"]

    name, _, digest = image.partition("@sha256:")
    assert name == "jasonish/suricata" and SHA256.fullmatch(digest)
    assert f"  {image} \\\n" in text("infra/sensor.service")


@pytest.mark.parametrize("wargame", sorted(WARGAMES))
def test_the_infra_sensor_reads_its_rules_where_the_platform_writes_them_and_reloads_by_suricatasc(wargame):
    sensor = definition(wargame).filling("sensor")
    unit = text("infra/sensor.service")
    rules = assigned("infra/install.sh")["RULES_DIR"]

    assert sensor.node == "cr-infra" and sensor.rules == f"{rules}/local.rules"
    assert sensor.reload.split()[0] == "suricatasc"
    assert "install -m 0755 suricatasc /usr/local/bin/suricatasc" in text("infra/install.sh")
    assert "docker exec -i sensor suricatasc" in text("infra/suricatasc")
    assert f"-v {rules}:{rules}" in unit and "--name sensor" in unit
    assert "--network host" in unit and "--af-packet=br0" in unit


def test_the_infra_ships_the_eve_log_suricata_writes():
    config = yaml.safe_load(text("infra/suricata.yaml").removeprefix(YAML_HEADER))
    [eve] = [output["eve-log"] for output in config["outputs"] if "eve-log" in output]
    written = f"{config['default-log-dir'].rstrip('/')}/{eve['filename']}"
    relay = text("infra/log-relay.conf")

    assert f'File="{written}" Tag="suricata"' in relay
    assert f"-v {assigned('infra/install.sh')['EVE_DIR']}:{config['default-log-dir'].rstrip('/')}" \
        in text("infra/sensor.service")


@pytest.mark.parametrize("slot", (1, 7, 42))
def test_every_line_the_infra_relays_names_a_sender_filebeat_takes_the_slot_from(slot):
    relay = filled("infra/log-relay.conf", slot=slot, log_server="10.40.0.10", collector="10.31.0.2")
    senders = re.findall(r"%TIMESTAMP:::date-rfc3339% (\S+) (\S+) ", relay)

    assert {tag for _, tag in senders} == {"modsecurity", "nginx", "suricata"}
    assert all(filebeat_slot(sender) == str(slot) for sender, _ in senders)
    assert relay.count(f'Target="10.31.0.2" Port="{fabric.COLLECTOR_PORT}" Protocol="udp"') == 3


@pytest.mark.parametrize("wargame", sorted(WARGAMES))
def test_the_infra_edge_forwards_the_web_port_to_the_waf_only_and_answers_ping_and_traceroute(wargame):
    env = next(node.env for node in planned(wargame).nodes if node.role == "infra")
    [(port, forwarded)] = device("cr-edge", wargame).forwards.items()
    edge = filled("infra/edge.nft", wan="wan", mgmt="mgmt", router=router_address(), waf=env["WAF_FRONT"])
    nat = edge.split("chain prerouting", 1)[1].split("}", 1)[0]
    forward = edge.split("chain forward", 1)[1].split("}", 1)[0]
    entered = edge.split("chain input", 1)[1].split("}", 1)[0]

    assert forwarded == "cr-waf" and env["WAF_FRONT"] == "10.30.0.247"
    assert [line.strip() for line in nat.splitlines() if "iifname" in line] == [
        f'iifname "wan" ip daddr {router_address()} tcp dport {port} dnat to 10.30.0.247']
    assert [line.strip() for line in forward.splitlines() if "iifname" in line] == [
        'iifname "wan" ct state established,related accept', 'iifname "wan" ct status dnat accept',
        'iifname "wan" drop'], "nothing from the internet reaches the slot but the DNAT'd web port and replies"
    assert 'iifname "wan" meta l4proto icmp accept' in entered
    assert 'iifname "wan" meta l4proto udp reject' in entered, "traceroute's last probe is answered port unreachable"
    assert entered.index('meta l4proto udp reject') < entered.index('iifname "wan" drop')
    assert "net.ipv4.ip_forward = 1" in text("infra/install.sh")


def test_the_infra_bridges_the_two_ids_legs_with_no_address_on_them():
    boot = text("infra/slot-boot")

    assert "Bridge=%s" in boot and "Kind=bridge" in boot
    assert 'ip addr flush dev "$leg"' in boot
    assert "tso off gso off gro off lro off" in boot, "the sensor sees the frames as they cross the wire"
    assert assigned("infra/slot-boot")["BRIDGE"] == "br0"


def test_docker_on_the_infra_leaves_the_edge_s_forwarding_alone():
    daemon = json.loads(text("infra/daemon.json"))

    assert daemon["iptables"] is False and daemon["bridge"] == "none"


def test_the_target_runs_both_wargames_by_the_images_ci_builds_at_the_baked_tag():
    tag = "abc"
    rendered = rendered_wargames(tag)
    images = sorted({service["image"] for document in rendered.values() for service in document["services"].values()})
    declared_images = sorted({re.sub(r"\$\{CR_IMAGE_TAG(?::-[^}]*)?\}", tag, service["image"])
                              for wargame in WARGAMES
                              for service in yaml.safe_load((ROOT / f"wargames/{wargame}/compose.yaml").read_text())[
                                  "services"].values()})

    assert assigned("target/install.sh")["WARGAMES"].strip('"').split() == sorted(WARGAMES)
    assert images == declared_images
    for document in rendered.values():
        for name, service in document["services"].items():
            assert "build" not in service
            assert service["container_name"] == name


def test_the_target_publishes_each_front_on_the_port_the_waf_proxies_to_and_keeps_the_databases_inside():
    proxied = dict(re.findall(r"proxy_pass http://([a-z-]+):(\d+);", text("waf/board.com.conf")))
    render = render_module()

    for wargame, document in rendered_wargames().items():
        networks = document["networks"]
        assert networks[render.BACKEND]["internal"] is True
        for name, service in document["services"].items():
            if name in proxied:
                port = proxied[name]
                assert service["ports"] == [f"${{{render.address_variable(wargame)}:?the slot names the "
                                            f"{wargame} address}}:{port}:{port}"]
                assert set(service["networks"]) == {render.BACKEND, render.FRONT}
            else:
                assert "ports" not in service and set(service["networks"]) == {render.BACKEND}


def test_the_target_limits_every_wargame_container_and_drops_its_capabilities():
    for wargame, document in rendered_wargames().items():
        for name, service in document["services"].items():
            assert service["cap_drop"] == ["ALL"] and "no-new-privileges:true" in service["security_opt"], name
            assert service["mem_limit"] and service["pids_limit"] == 256, name
            assert service["restart"] == "no", "a fresh stack is the pristine state; nothing restarts on its own"


def test_the_target_s_containers_are_the_devices_its_topology_names_and_fronts_the_upstreams_the_waf_proxies():
    render = render_module()
    fronts = yaml.safe_load(text("target/wargames.yaml"))["fronts"]

    for wargame, document in rendered_wargames().items():
        placed = {one.container for one in definition(wargame).devices.values() if one.container}
        assert placed == set(document["services"]), "the map and ground truth find each container by name"
        assert {name for name in document["services"] if name in fronts} == {
            one.container for one in definition(wargame).devices.values() if wargame in one.roles}
        [port] = [one for one in definition(wargame).ports if one.node == "cr-target"]
        assert device("cr-waf", wargame).upstreams[wargame] == port.address
        assert render.address_variable(wargame) == f"{wargame.upper()}_ADDRESS"


def test_the_target_keeps_pristine_data_and_restores_it_into_empty_volumes_only():
    install = text("target/install.sh")
    boot = text("target/wargames")

    assert 'cp -a "$source/." "$KEPT/$service$path/"' in install
    assert 'compose "$1" down -v --timeout 1' in install
    assert '[ -z "$(ls -A "$source")" ] || continue' in boot
    assert 'cp -a "$KEPT/$service$path/." "$source/"' in boot
    assert boot.index("up --no-start --pull never") < boot.index("restored ") < boot.index("up -d --wait")
