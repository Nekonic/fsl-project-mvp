import ipaddress
import pathlib
import re

import yaml

import attacker
from range import rangehost

DEPLOY = pathlib.Path(attacker.__file__).resolve().parents[1] / "deploy"


def test_the_kali_image_ships_the_source_rewrite_script():
    image = (DEPLOY / "kali/Dockerfile").read_text()
    script = (DEPLOY / "kali/set-origin").read_text()

    assert "COPY kali/set-origin /usr/local/sbin/set-origin" in image
    assert "SNAT" in script and "--to-source" in script


def test_nothing_in_the_kali_image_that_a_learner_can_list_carries_the_platform_s_name():
    image = (DEPLOY / "kali/Dockerfile").read_text()
    script = (DEPLOY / "kali/set-origin").read_text()

    assert not re.search(r"\bcr[-_.]", image + script), "ps and iptables in the container print these names"
    assert "ORIGIN-SNAT" in script


def test_the_label_file_is_read_only_to_the_root_the_platform_runs_its_commands_as():
    image = (DEPLOY / "kali/Dockerfile").read_text()

    assert "install -m 0600 /dev/null /var/lib/session/active" in image
    assert "/var/lib/session/origin" not in image


def test_the_waf_answers_to_waf_and_its_log_sender_name_keeps_its_slot():
    services = yaml.safe_load((DEPLOY / "range-host/slot.yaml").read_text())["services"]
    slot = rangehost.Slot(2, ipaddress.ip_network("10.30.2.0/24"), "abc", 1442)

    assert services["waf"]["hostname"] == "waf"
    assert " cr-waf-2 " in rangehost.forwarding(slot, "10.31.0.2", 5140, {"waf": ("cr-waf", "modsecurity")}), (
        "Filebeat takes the slot from the syslog host name, which the fixed name would erase"
    )
