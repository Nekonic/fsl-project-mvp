import pytest

CONTROL = "board-sqli-search"
SECOND_SHAPE = "board-sqli-union-search"

@pytest.fixture(scope="module")
def fired(full_run):
    return full_run["score"], {d["detection_id"]: d for d in full_run["detections"]}

def _case(fired, name):
    score, _ = fired
    return next(c for c in score["per_case"] if c["name"] == name)

def _engines(fired, name):
    _, by_id = fired
    return {
        by_id[d]["source"] for d in _case(fired, name)["detection_ids"] if d in by_id
    }

def test_both_encodings_are_detected_and_each_engine_sees_the_attack_not_one_shape(fired):
    assert _case(fired, CONTROL)["verdict"] == "TP"
    assert _case(fired, SECOND_SHAPE)["verdict"] == "TP"
    assert {"suricata", "modsecurity"} <= _engines(fired, CONTROL)
    assert "suricata" in _engines(fired, SECOND_SHAPE), (
        f"only {sorted(_engines(fired, SECOND_SHAPE))} caught the union-select "
        f"injection - the IDS rules match one SQLi shape rather than the attack, "
        f"and the WAF is covering for them"
    )
