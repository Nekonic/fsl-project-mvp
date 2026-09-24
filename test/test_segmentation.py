import pytest
import requests

from conftest import PLATFORM_URL
from range import ATTACKER, GATEWAY, TARGET, run, segments

TARGET_INSIDE = "http://juice-shop:3000/"
WAF_INSIDE = "http://shop.com/"

def _from_kali(url, extra=()):
    return run(
        ATTACKER,
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
         "--max-time", "8", "--noproxy", "*", *extra, url],
    )

def test_the_attacker_cannot_reach_the_target_directly(stack_is_up):
    result = _from_kali(TARGET_INSIDE)

    assert result.stdout.strip() != "200", (
        "the attacker reached the target without passing the WAF, so the "
        "defence is optional and every score is meaningless"
    )

def test_the_attacker_can_still_reach_the_way_in(stack_is_up):
    result = _from_kali(WAF_INSIDE)

    assert result.stdout.strip() == "200", (
        f"the attacker cannot reach the WAF either ({result.stdout.strip()}), "
        f"so the range is broken rather than segmented"
    )

def test_the_attacker_and_the_target_share_no_segment(stack_is_up):
    attacker = segments(ATTACKER)
    target = segments(TARGET)

    assert not (attacker & target), (
        f"attacker and target both sit on {sorted(attacker & target)}, so "
        f"nothing but hostnames stands between them"
    )

def test_the_waf_is_the_only_way_across(stack_is_up):
    attacker = segments(ATTACKER)
    target = segments(TARGET)
    waf = segments(GATEWAY)

    assert attacker & waf, "the WAF is not reachable from the attacker's segment"
    assert target & waf, "the WAF cannot reach the target's segment"

def test_the_attacker_comes_from_somewhere_the_map_can_place(stack_is_up):
    source_ip = requests.get(f"{PLATFORM_URL}/api/attacker/", timeout=60).json()["source_ip"]

    located = requests.post(
        "http://localhost:9200/_ingest/pipeline/fsl-geoip/_simulate",
        json={"docs": [{"_source": {"src_ip": source_ip}}]}, timeout=60,
    ).json()["docs"][0]["doc"]["_source"]

    assert "src_geo" in located, f"{source_ip} geolocates to nothing"
    assert located["src_geo"]["location"]["lat"]
