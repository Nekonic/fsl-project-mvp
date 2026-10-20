import pathlib

import attacker
from range.ports import Ran

def test_the_kali_image_ships_the_source_rewrite_script():
    setup = (pathlib.Path(attacker.__file__).resolve().parents[1] / "deploy/kali/setup.sh").read_text()

    assert "/usr/local/sbin/set-origin" in setup
    assert "SNAT" in setup and "--to-source" in setup

def test_nothing_on_the_kali_vm_that_a_learner_can_list_carries_the_platform_s_name():
    root = pathlib.Path(attacker.__file__).resolve().parents[1] / "deploy"
    setup = (root / "kali/setup.sh").read_text()

    assert "fsl" not in setup.lower(), "systemctl, ps and iptables on the box print these names"
    assert "web-proxy.service" in setup and "ttyd.service" in setup and "ORIGIN-SNAT" in setup

def test_the_label_and_origin_files_are_read_only_to_the_account_the_platform_logs_in_as():
    setup = (pathlib.Path(attacker.__file__).resolve().parents[1] / "deploy/kali/setup.sh").read_text()

    for name in ("active", "origin"):
        assert f"install -m 0600 -o ubuntu -g ubuntu /dev/null /var/lib/session/{name}" in setup

def test_the_waf_vm_answers_to_waf_and_keeps_its_slot_in_the_log_sender_name():
    setup = (pathlib.Path(attacker.__file__).resolve().parents[1] / "deploy/waf/setup.sh").read_text()

    assert "echo waf > /etc/hostname" in setup and "hostname waf" in setup
    assert 'global(localHostname="%s")' in setup, (
        "Filebeat takes the slot from the syslog host name, which the fixed name would erase"
    )
