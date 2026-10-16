BOARD = "http://board.com"


def _from_range(path):
    from range import ATTACKER, run

    out = run(ATTACKER, ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                         "--max-time", "20", f"{BOARD}{path}"])
    return out.stdout.strip()


def test_sorting_by_a_real_column_works(stack_is_up):
    assert _from_range("/?sort=title") == "200"
    assert _from_range("/?sort=-created_at") == "200"


def test_an_unknown_sort_field_errors_proving_user_input_reaches_order_by(stack_is_up):
    assert _from_range("/?sort=nope__nope") == "500", (
        "an unknown sort field did not error, so the ?sort value is ignored and "
        "never reaches order_by; the injection sink is not wired"
    )


def test_the_internal_ground_truth_is_blocked_through_the_waf(stack_is_up):
    assert _from_range("/internal/auth-users") == "404", (
        "the attacker-facing WAF served the internal ground-truth path; it must "
        "be reachable only platform->board over estate, never through board.com"
    )


def test_the_internal_ground_truth_is_blocked_by_any_host(stack_is_up):
    from range import ATTACKER, run

    waf = run(ATTACKER, ["getent", "hosts", "board.com"]).stdout.split()[0]
    code = run(ATTACKER, ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                          "--max-time", "20", "-H", "Host: not-board",
                          f"http://{waf}/internal/auth-users"]).stdout.strip()
    assert code == "404", (
        "the WAF default vhost served /internal to a non-board.com Host; the "
        "ground truth must be reachable only platform->board over estate"
    )
