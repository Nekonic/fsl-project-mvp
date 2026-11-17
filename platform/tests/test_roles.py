import importlib.util
import ipaddress
import re
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

from range import fabric, rangehost
from wargames import WARGAMES

ROOT = Path(__file__).resolve().parents[2]
ROLES = ROOT / "deploy/roles"
SCRIPTS = ("kali/install.sh", "kali/slot-boot", "waf/install.sh", "waf/slot-boot", "infra/install.sh",
           "infra/slot-boot", "infra/suricatasc", "target/install.sh", "target/wargames")
SLOT_TEMPLATE = ROOT / "deploy/range-host/slot.yaml"
FILEBEAT = ROOT / "deploy/filebeat/filebeat.yml"
DECLARATION = ROOT / "platform/range/declaration.yaml"


def text(role_file: str) -> str:
    return (ROLES / role_file).read_text()


def assigned(role_file: str) -> dict[str, str]:
    return {name: value.strip('"') for name, value in
            re.findall(r'^([A-Z_0-9]+)=("[^"]*"|\S+)$', text(role_file), re.M)}


def dockerfile_args(path: str) -> dict[str, str]:
    return dict(re.findall(r"^ARG (\w+)=(\S+)$", (ROOT / path).read_text(), re.M))


def dockerfile_packages(path: str) -> set[str]:
    run = (ROOT / path).read_text().split("apt-get install -y", 1)[1].split("&&", 1)[0]
    return set(run.replace("\\", " ").split())


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


def slot_template() -> dict:
    return yaml.safe_load(SLOT_TEMPLATE.read_text())


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
def test_a_role_carries_the_file_the_container_range_runs_not_a_copy_that_could_drift(carried, source):
    assert (ROLES / carried).resolve() == (ROOT / source).resolve()


def test_kali_installs_the_headless_set_and_every_package_the_kali_container_has():
    named = assigned("kali/install.sh")
    installed = re.search(r"^installed (.+)$", text("kali/install.sh"), re.M)[1].split()
    packages = {word for word in installed if not word.startswith("$")}
    packages |= {package for word in installed if word.startswith("$") for package in named[word[1:]].split()}

    assert {"kali-linux-headless", "iputils-ping", "traceroute"} <= packages
    assert dockerfile_packages("deploy/kali/Dockerfile") <= packages


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
    router = rangehost.router_address()
    hosts = slot_template()["services"]["kali"]["extra_hosts"]

    assert assigned("kali/install.sh")["ROUTER"] == router
    assert assigned("kali/slot-boot")["ROUTER"] == router
    assert hosts == ["board.com:@router@", "corp.com:@router@"]
    assert "'%s board.com\\n%s corp.com\\n'" in text("kali/install.sh")
    assert 'ip route replace default via "$ROUTER" dev "$internet" onlink src "$source"' in text("kali/slot-boot")


def test_nothing_kali_installs_that_a_learner_can_list_carries_the_platform_s_name():
    for name in ("install.sh", "slot-boot", "slot-boot.service", "web-proxy.service"):
        assert not re.search(r"\bcr[-_.]", text(f"kali/{name}")), name


def test_the_waf_builds_the_versions_the_waf_container_pins():
    pinned = dockerfile_args("deploy/waf/Dockerfile")
    built = assigned("waf/install.sh")

    for name in ("MODSECURITY", "MODSECURITY_SHA256", "CONNECTOR", "CONNECTOR_SHA256", "NGINX", "NGINX_SHA256",
                 "CRS", "CRS_SHA256", "RELEASES", "CRS_RELEASES"):
        assert built[name] == pinned[name], name


def test_the_waf_ships_the_audit_and_refused_logs_under_the_tags_filebeat_decodes():
    audit = re.search(r"^SecAuditLog (\S+)$", text("waf/modsecurity.conf"), re.M)[1]
    refused = re.search(r"^access_log (\S+) refused", text("waf/board.com.conf"), re.M)[1]
    shipped = dict((tag, path) for path, tag in
                   re.findall(r'File="([^"]+)" Tag="([^"]+)"', text("waf/log-shipper.conf")))
    filebeat = yaml.safe_dump(yaml.safe_load(FILEBEAT.read_text()))

    assert shipped == {"modsecurity": audit, "nginx": refused}
    assert {tag for tag, _ in rangehost.LOGS["waf"]} == set(shipped)
    assert all(f"log.syslog.appname: {tag}" in filebeat for tag in shipped)
    assert assigned("waf/install.sh")["AUDIT_LOG"] == audit
    assert assigned("waf/install.sh")["REFUSED_LOG"] == refused


def test_the_waf_ships_to_the_slot_log_server_by_tcp_on_the_port_the_infra_listens_on():
    shipper = filled("waf/log-shipper.conf", log_server="10.40.0.10")

    assert f'Target="10.40.0.10" Port="{rangehost.SHIPPED_PORT}" Protocol="tcp"' in shipper
    assert f'port="{rangehost.SHIPPED_PORT}" ruleset="relayed"' in text("infra/log-relay.conf")
    assert f'tcp dport {rangehost.SHIPPED_PORT} accept' in text("infra/edge.nft")


def test_the_waf_validates_its_configuration_and_reloads_as_the_platform_asks():
    declared = yaml.safe_load(DECLARATION.read_text())["hosts"]["cr-waf"]
    script = text("waf/install.sh")

    assert declared["rules"] == f"{assigned('waf/install.sh')['MODSEC_DIR']}/crs/rules/" \
                                "REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf"
    assert '[ -f "$EXCLUSIONS" ] || install -m 664 -g adm /dev/null "$EXCLUSIONS"' in script
    assert "nginx -t\n" in script
    assert "Before=nginx.service" in text("waf/slot-boot.service"), "nginx resolves board and corp-wp when it starts"


def test_the_waf_and_the_target_agree_on_the_names_of_the_wargames_addresses():
    render = render_module()
    boot = text("waf/slot-boot")

    for wargame in sorted(WARGAMES):
        assert f"${render.address_variable(wargame)}" in boot


def test_the_infra_runs_the_sensor_image_the_container_range_pins():
    image = slot_template()["x-sensor"]["image"]

    assert assigned("infra/install.sh")["SENSOR_IMAGE"] == image
    assert f"  {image} \\\n" in text("infra/sensor.service")


def test_the_infra_sensor_reads_its_rules_where_the_platform_writes_them_and_reloads_by_suricatasc():
    declared = yaml.safe_load(DECLARATION.read_text())["hosts"]["cr-range"]
    unit = text("infra/sensor.service")
    rules = assigned("infra/install.sh")["RULES_DIR"]

    assert declared["rules"] == f"{rules}/local.rules"
    assert declared["reload"].split()[0] == "suricatasc"
    assert "install -m 0755 suricatasc /usr/local/bin/suricatasc" in text("infra/install.sh")
    assert "docker exec -i sensor suricatasc" in text("infra/suricatasc")
    assert f"-v {rules}:{rules}" in unit and "--name sensor" in unit
    assert "--network host" in unit and "--af-packet=br0" in unit


def test_the_infra_ships_the_eve_log_suricata_writes():
    config = yaml.safe_load(text("infra/suricata.yaml").removeprefix(rangehost.YAML_HEADER))
    [eve] = [output["eve-log"] for output in config["outputs"] if "eve-log" in output]
    written = f"{config['default-log-dir'].rstrip('/')}/{eve['filename']}"
    relay = text("infra/log-relay.conf")

    assert f'File="{written}" Tag="suricata"' in relay
    assert {tag for tag, _ in rangehost.LOGS["sensor"]} == {"suricata"}
    assert f"-v {assigned('infra/install.sh')['EVE_DIR']}:{config['default-log-dir'].rstrip('/')}" \
        in text("infra/sensor.service")


@pytest.mark.parametrize("slot", (1, 7, 42))
def test_every_line_the_infra_relays_names_a_sender_filebeat_takes_the_slot_from(slot):
    relay = filled("infra/log-relay.conf", slot=slot, log_server="10.40.0.10", collector="10.31.0.2")
    senders = re.findall(r"%TIMESTAMP:::date-rfc3339% (\S+) (\S+) ", relay)

    assert {tag for _, tag in senders} == {"modsecurity", "nginx", "suricata"}
    assert all(filebeat_slot(sender) == str(slot) for sender, _ in senders)
    assert relay.count(f'Target="10.31.0.2" Port="{fabric.COLLECTOR_PORT}" Protocol="udp"') == 3


def test_the_infra_edge_keeps_the_container_edge_s_forwarding_rules_and_answers_ping_and_traceroute():
    slot = rangehost.Slot(1, ipaddress.ip_network("10.30.1.0/24"), "abc", 1442)
    document = rangehost.compose(ROOT, slot, sorted(WARGAMES))
    waf = rangehost.addressed(document, rangehost.FRONT)[rangehost.WAF]
    expected = [line.strip() for line in rangehost.edge_rules(document).splitlines() if line.strip().startswith("iifname")]
    edge = filled("infra/edge.nft", wan="wan", mgmt="mgmt", router=rangehost.router_address(), waf=waf)
    forward = edge.split("chain forward", 1)[1].split("}", 1)[0]
    entered = edge.split("chain input", 1)[1].split("}", 1)[0]

    assert all(line in edge for line in expected), expected
    assert [line.strip() for line in forward.splitlines() if "iifname" in line] == expected[1:]
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
    import json

    daemon = json.loads(text("infra/daemon.json"))

    assert daemon["iptables"] is False and daemon["bridge"] == "none"


def test_the_target_runs_both_wargames_by_the_images_the_range_host_pulls():
    tag = "abc"
    rendered = rendered_wargames(tag)
    images = sorted({service["image"] for document in rendered.values() for service in document["services"].values()})

    assert assigned("target/install.sh")["WARGAMES"].strip('"').split() == sorted(WARGAMES)
    slot = rangehost.Slot(1, ipaddress.ip_network("10.30.1.0/24"), tag, 1442)
    document = rangehost.compose(ROOT, slot, sorted(WARGAMES))
    pulled_today = sorted({document["services"][name]["image"] for name in rangehost.wargame_services(document)})

    assert images == pulled_today
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


def test_the_target_keeps_the_limits_the_range_host_gives_the_wargames():
    template = slot_template()
    declared = template["x-wargames"]
    settings = yaml.safe_load(text("target/wargames.yaml"))

    assert settings["limits"] == declared["limits"]
    assert settings["extra_hosts"] == declared["extra_hosts"]
    assert settings["healthcheck"] == declared["healthcheck"]
    assert settings["contained"] == template["x-contained"]
    assert set(settings["fronts"]) == set(declared["fronts"])


def test_the_target_keeps_pristine_data_and_restores_it_into_empty_volumes_only():
    install = text("target/install.sh")
    boot = text("target/wargames")

    assert 'cp -a "$source/." "$KEPT/$service$path/"' in install
    assert 'compose "$1" down -v --timeout 1' in install
    assert '[ -z "$(ls -A "$source")" ] || continue' in boot
    assert 'cp -a "$KEPT/$service$path/." "$source/"' in boot
    assert boot.index("up --no-start --pull never") < boot.index("restored ") < boot.index("up -d --wait")
