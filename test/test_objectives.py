def test_a_breach_is_scored_and_attributed_to_the_attack_that_took_it(board_session):
    submitted = board_session["real_loot"]
    case_id = board_session["case_id"]
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["credited"], "the exfiltrated hashes credited no tier"

    scored = board_session["scored"]
    own = board_session["own"]

    assert own.get("detection_ids"), (
        f"the attack that took the loot (case {case_id}) drew no detection, so a "
        f"breach credited to it reads exactly like one credited to nothing"
    )
    assert scored["breaches"], "nothing was taken, so attribution proves nothing"
    for breach in scored["breaches"]:
        assert (breach["detected"], sorted(breach["detection_ids"])) == (
            own["detected"], sorted(own["detection_ids"])
        ), (
            f"the loot was windowed to case {case_id}, so each breach must carry "
            f"that case's detections; {breach['key']} carried something else"
        )
