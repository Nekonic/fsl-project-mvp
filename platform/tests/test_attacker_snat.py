import pathlib
import re

import attacker

DEPLOY = pathlib.Path(attacker.__file__).resolve().parents[1] / "deploy"


def test_nothing_in_the_set_origin_script_a_learner_can_list_carries_the_platform_s_name():
    script = (DEPLOY / "kali/set-origin").read_text()

    assert not re.search(r"\bcr[-_.]", script), "ps and iptables on Kali print these names"
    assert "ORIGIN-SNAT" in script
