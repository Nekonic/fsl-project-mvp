from range import ATTACKER, run

PAST_THE_WAF = ("http://board:8000/", "http://corp-wp/")

def test_the_attacker_cannot_reach_a_target_past_the_waf():
    reached = {
        url: run(ATTACKER, ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                            "--max-time", "8", "--noproxy", "*", url]).stdout.strip()
        for url in PAST_THE_WAF
    }

    assert all(code in ("", "000") for code in reached.values()), (
        f"the attacker reached a target directly ({reached}), so the WAF is optional"
    )
