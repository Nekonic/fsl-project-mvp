
from range import ATTACKER, run, segments

BOARD = "board"
TARGET_INSIDE = "http://board:8000/"
WAF_INSIDE = "http://board.com/"

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
    target = segments(BOARD)

    assert not (attacker & target), (
        f"attacker and target both sit on {sorted(attacker & target)}, so "
        f"nothing but hostnames stands between them"
    )
