import plays


def kept_everywhere(objectives: list[dict]) -> bool:
    return {line["key"] for line in objectives} == set(plays.objective_keys("board")) and (
        {line["state"] for line in objectives} == {"kept"})


def test_loot_with_one_digest_changed_is_refused_against_the_round_start_snapshot(board_round):
    submitted = board_round["fabricated_loot"]

    assert submitted.status == 200, submitted.text
    assert submitted.body["lost"] is False, submitted.body
    assert kept_everywhere(board_round["objectives_after_fabricated"]), board_round["objectives_after_fabricated"]


def test_the_previous_round_s_true_digests_are_refused_in_the_next_round(board_round):
    submitted = board_round["stale_loot"]

    assert submitted.status == 200, submitted.text
    assert submitted.body["lost"] is False, (
        f"loot that matched the last round's secret took an objective in the next; the secret is set at random "
        f"at each round's start: {submitted.body}")
    assert kept_everywhere(board_round["objectives_after_stale"]), board_round["objectives_after_stale"]


def test_a_loot_answer_never_carries_the_secret(board_round):
    shown = board_round["real_loot"].text + board_round["fabricated_loot"].text
    leaked = [name for name, digest in board_round["truth"].items() if digest in shown]

    assert leaked == [], f"a loot answer carried the stored digest of {leaked}"
