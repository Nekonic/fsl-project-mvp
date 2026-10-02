import pathlib

import pytest

import attacker
from attacker import AttackerUnavailable
from range.ports import Ran

CHOSEN = {"id": "us", "source_ip": "73.0.0.10", "address": "73.0.0.1"}

def test_host_rewrite_mode_writes_the_gateway_address_to_the_origin_file(settings):
    settings.ATTACKER_ORIGIN_MODE = "host-rewrite"
    settings.ATTACKER_ORIGIN_FILE = "/label/origin"
    seen = []

    def runner(argv, stdin=None, timeout=60.0):
        seen.append((argv, stdin))
        return Ran(0, "")

    attacker.wear_origin(CHOSEN, runner)

    assert seen == [(["sh", "-c", "cat > /label/origin"], "73.0.0.1")]

def test_snat_mode_runs_the_source_rewrite_with_the_origins_own_address(settings):
    settings.ATTACKER_ORIGIN_MODE = "snat"
    seen = []

    def runner(argv, stdin=None, timeout=60.0):
        seen.append(argv)
        return Ran(0, "")

    attacker.wear_origin(CHOSEN, runner)

    assert seen == [["sudo", "/usr/local/sbin/fsl-origin", "73.0.0.10"]]

def test_a_rewrite_the_box_refused_is_unavailable(settings):
    settings.ATTACKER_ORIGIN_MODE = "snat"

    def refusing(argv, stdin=None, timeout=60.0):
        return Ran(1, "iptables: Permission denied")

    with pytest.raises(AttackerUnavailable, match="Permission denied"):
        attacker.wear_origin(CHOSEN, refusing)

def test_the_kali_image_ships_the_source_rewrite_script():
    setup = (pathlib.Path(attacker.__file__).resolve().parents[1] / "deploy/kali/setup.sh").read_text()

    assert "/usr/local/sbin/fsl-origin" in setup
    assert "SNAT" in setup and "--to-source" in setup
