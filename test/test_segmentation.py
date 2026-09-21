"""The defence must not be optional.

Everything used to sit on one flat bridge, so the attacker could reach the
target directly and both the WAF and the IDS vanished - same payload, one
`--noproxy` flag, zero alerts. A score taken under those conditions says the
defence was perfect while nothing was defended.

These check the shape of the network, not a rule. A range whose defence can be
stepped around is not measuring a defence.
"""

import json
import subprocess

import pytest
import requests

from conftest import PLATFORM_URL

TARGET_INSIDE = "http://juice-shop:3000/"
# The way in, under the name anyone would dial. The port is the site's,
# not the appliance's - see DECISIONS.
WAF_INSIDE = "http://shop.com/"


def _from_kali(url, extra=()):
    """Reach for something from the attacker's box, bypassing its proxy."""
    return subprocess.run(
        [
            "docker", "exec", "fsl-kali", "curl", "-s", "-o", "/dev/null",
            "-w", "%{http_code}", "--max-time", "8", "--noproxy", "*", *extra, url,
        ],
        capture_output=True, text=True, timeout=60,
    )


def _networks(container):
    out = subprocess.run(
        ["docker", "inspect", container, "--format", "{{json .NetworkSettings.Networks}}"],
        capture_output=True, text=True, timeout=60, check=True,
    )
    return json.loads(out.stdout)


def test_the_attacker_cannot_reach_the_target_directly(stack_is_up):
    # The whole point. Whether it fails to resolve or fails to connect does
    # not matter; being answered does.
    result = _from_kali(TARGET_INSIDE)

    assert result.stdout.strip() != "200", (
        "the attacker reached the target without passing the WAF, so the "
        "defence is optional and every score is meaningless"
    )


def test_the_attacker_can_still_reach_the_way_in(stack_is_up):
    # A segmentation that also breaks the front door proves nothing.
    result = _from_kali(WAF_INSIDE)

    assert result.stdout.strip() == "200", (
        f"the attacker cannot reach the WAF either ({result.stdout.strip()}), "
        f"so the range is broken rather than segmented"
    )


def test_the_attacker_and_the_target_share_no_network(stack_is_up):
    attacker = set(_networks("fsl-kali"))
    target = set(_networks("fsl-juice-shop"))

    assert not (attacker & target), (
        f"attacker and target both sit on {sorted(attacker & target)}, so "
        f"nothing but hostnames stands between them"
    )


def test_the_waf_is_the_only_way_across(stack_is_up):
    attacker = set(_networks("fsl-kali"))
    target = set(_networks("fsl-juice-shop"))
    waf = set(_networks("fsl-waf"))

    assert attacker & waf, "the WAF is not reachable from the attacker's segment"
    assert target & waf, "the WAF cannot reach the target's segment"


def test_the_attacker_comes_from_somewhere_the_map_can_place(stack_is_up):
    # Private addresses resolve to nothing, so a range on RFC 1918 has no map
    # and no country to show. The attacker sits on public space on purpose.
    source_ip = requests.get(f"{PLATFORM_URL}/api/attacker/", timeout=60).json()["source_ip"]

    located = requests.post(
        "http://localhost:9200/_ingest/pipeline/fsl-geoip/_simulate",
        json={"docs": [{"_source": {"src_ip": source_ip}}]}, timeout=60,
    ).json()["docs"][0]["doc"]["_source"]

    assert "src_geo" in located, f"{source_ip} geolocates to nothing"
    assert located["src_geo"]["location"]["lat"]
