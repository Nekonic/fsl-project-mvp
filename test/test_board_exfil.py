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


def test_members_endpoint_leaks_real_password_hashes(stack_is_up):
    from range import ATTACKER, run

    body = run(ATTACKER, ["curl", "-s", "--max-time", "20",
                          f"{BOARD}/members.json"]).stdout
    import json

    users = json.loads(body)["users"]
    names = {u["username"] for u in users}
    assert {"admin", "jiwoo", "minseo"} <= names
    assert all(u["password"].startswith("pbkdf2_sha256$") for u in users), (
        "the endpoint did not return the stored hash column"
    )


def test_the_internal_ground_truth_is_blocked_through_the_waf(stack_is_up):
    assert _from_range("/internal/auth-users") == "404", (
        "the attacker-facing WAF served the internal ground-truth path; it must "
        "be reachable only platform->board over estate, never through board.com"
    )


def test_the_platform_reads_the_auth_user_hashes_over_estate(stack_is_up):
    from range import SCORER, run

    body = run(SCORER, ["curl", "-s", "--max-time", "20",
                        "http://board:8000/internal/auth-users"]).stdout
    import json

    truth = json.loads(body)
    assert {"admin", "jiwoo", "minseo"} <= set(truth), truth
    assert all(h.startswith("pbkdf2_sha256$") for h in truth.values()), (
        "the internal endpoint did not return the stored salted-hash column"
    )
