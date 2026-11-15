import pytest


def indiscriminate(totals, sigs):
    found = set()
    for case in totals["per_case"]:
        if not case["malicious"]:
            found |= {sigs[i] for i in case["detection_ids"] if i in sigs}
    return found


@pytest.fixture(scope="module")
def block_everything(rules_session):
    after = rules_session["after"]
    phase = [case for case in after["per_case"] if case["case_id"] in rules_session["catch_all"]]
    totals = {
        "per_case": phase,
        "tp": sum(case["verdict"] == "TP" for case in phase),
        "fp": sum(case["verdict"] == "FP" for case in phase),
        "warnings": after["warnings"],
    }
    return totals, {d["detection_id"]: d["signature"] for d in rules_session["listed"]}


def test_the_experiment_is_valid_at_all(block_everything):
    totals, sigs = block_everything

    assert len(totals["per_case"]) == 5, totals["per_case"]
    assert totals["fp"] > 0 and totals["tp"] > 0, (
        f"the catch-all rule did not fire on both attacks and benign traffic, "
        f"so nothing below proves anything: {totals['tp']}/{totals['fp']}"
    )
    assert indiscriminate(totals, sigs), (
        "no signature fired on both, so there is no indiscriminate defence here"
    )


def test_nothing_is_credited_to_a_signature_that_also_fires_on_benign_traffic(
    block_everything,
):
    totals, sigs = block_everything
    noise = indiscriminate(totals, sigs)

    for case in totals["per_case"]:
        if not (case["malicious"] and case["corroborated"] is True):
            continue
        own = {sigs[i] for i in case["detection_ids"] if i in sigs}
        assert own - noise, (
            f"{case['name']} was credited with a real detection, and every "
            f"signature it drew also fired on traffic meant to pass: {own}. "
            f"The defence writes that text, so a block-everything rule set "
            f"wins the one number meant to stop it"
        )


def test_a_defence_with_nothing_but_noise_is_called_out(block_everything):
    totals, sigs = block_everything
    noise = indiscriminate(totals, sigs)

    only_noise = [
        c["name"] for c in totals["per_case"]
        if c["malicious"] and c["expect"]
        and not ({sigs[i] for i in c["detection_ids"] if i in sigs} - noise)
    ]

    assert only_noise, (
        "every attack drew at least one discriminating alert, so this run "
        "cannot show the check biting - ModSecurity caught them all"
    )
    for name in only_noise:
        case = next(c for c in totals["per_case"] if c["name"] == name)
        assert case["corroborated"] is False, (
            f"{name} drew nothing but indiscriminate alerts and still reports "
            f"corroborated={case['corroborated']!r}"
        )
    wrong = [c["name"] for c in totals["per_case"] if c["detected"] and c["corroborated"] is False]
    assert wrong and any(
        w[0] == "score.warning.wrong_reason" and all(name in w[1] for name in wrong)
        for w in totals["warnings"]
    ), totals["warnings"]
