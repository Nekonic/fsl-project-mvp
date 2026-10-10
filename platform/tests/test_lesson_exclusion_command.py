import re
import subprocess

import pytest

import wargames
from rules import crs

HAND_WRITTEN = range(10100, 10200)
COMMAND = next(step["command"] for step in wargames.lesson("board")["steps"] if step["id"] == "exclude")
RULE_ID = re.compile(r'"id:(\d+),')


def run(tmp_path, before, nginx_passes=True):
    rules = tmp_path / "REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf"
    rules.write_text(before)
    tools = tmp_path / "bin"
    tools.mkdir(exist_ok=True)
    (tools / "nginx").write_text(f"#!/bin/sh\n[ \"$1\" = -t ] && exit {0 if nginx_passes else 1}\nexit 0\n")
    (tools / "nginx").chmod(0o755)
    done = subprocess.run(["sh", "-c", COMMAND.replace(crs.EXCLUSIONS, str(rules))], capture_output=True, text=True,
                          env={"PATH": f"{tools}:/usr/bin:/bin"})
    return rules.read_text(), done


def ids(text):
    return [int(found) for found in RULE_ID.findall(text)]


def test_the_command_writes_into_the_waf_s_own_exclusion_file():
    assert crs.EXCLUSIONS in COMMAND


def test_the_hand_written_id_is_outside_every_id_the_platform_s_tuning_renders():
    tuning = crs.checked({"paranoia": 4, "exclusions": [
        {"rule_id": 920273, "target": "ARGS:q", "path": "/search/"}] * crs.MOST_EXCLUSIONS})

    rendered = ids(crs.rendered(tuning))

    assert set(ids(COMMAND)) <= set(HAND_WRITTEN)
    assert not set(rendered) & set(HAND_WRITTEN), "the PUT /waf/ ids and the hand-written ids never meet"


def test_running_the_command_after_a_tuning_leaves_every_id_unique(tmp_path):
    rendered = crs.rendered(crs.checked({"paranoia": 4, "exclusions": [
        {"rule_id": 942100, "target": "", "path": "/posts/"}]}))

    after, done = run(tmp_path, rendered)

    assert done.returncode == 0, done.stderr
    assert after.startswith(rendered)
    assert len(ids(after)) == len(set(ids(after))) == 3


def test_running_the_command_twice_keeps_one_copy_of_the_rule(tmp_path):
    once, _ = run(tmp_path, "")
    twice, _ = run(tmp_path, once)

    assert twice == once and ids(twice) == [10100]
    assert crs.parsed(twice)["exclusions"] == [{"rule_id": 920273, "target": "ARGS:q", "path": "/search/"}]


def test_a_rule_nginx_refuses_puts_the_previous_file_back(tmp_path):
    before = 'SecAction "id:10000,phase:1,pass,nolog,setvar:tx.blocking_paranoia_level=4"\n'

    after, done = run(tmp_path, before, nginx_passes=False)

    assert after == before, "the WAF is never left on a file nginx refused"
    assert "previous file is back" in done.stdout


@pytest.mark.parametrize("before", ["", "SecRule ARGS \"@rx x\" \"id:10100,phase:1,deny\"\n"])
def test_an_older_hand_written_rule_with_the_same_id_is_replaced(tmp_path, before):
    after, _ = run(tmp_path, before)

    assert ids(after) == [10100] and "ruleRemoveTargetById=920273;ARGS:q" in after
