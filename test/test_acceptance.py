"""설계 문서 9장의 완료 기준을 검증한다.

3번(TP > 0, TN > 0)이 이 MVP 의 반증 지점이다. TP 가 0이면 경보-케이스
대응이 실패한 것이고, TN 이 0이면 오탐 채점이 무의미한 것이다.
"""

import requests

from conftest import PLATFORM_URL, TARGET_URL, run_redteam, score_when_ready

NOISY_RULE = (
    '\nalert http any any -> any any (msg:"FSL 의도적 오탐 룰"; '
    'http.uri; content:"apple"; nocase; sid:9009999; rev:1;)\n'
)


def test_criterion_1_services_answer():
    """완료 기준 1: 스택이 떠 있다."""
    assert requests.get(f"{PLATFORM_URL}/api/rules/", timeout=5).ok
    assert requests.get(TARGET_URL, timeout=5).status_code < 500
    assert requests.get("http://localhost:9200/_cluster/health", timeout=5).ok


def test_criterion_2_redteam_run_produces_a_closed_session(session_id):
    """완료 기준 2: 레드팀이 완주하고 세션 번호를 낸다."""
    response = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/")

    assert response.ok
    assert response.json()["ended_at"] is not None


def test_ground_truth_contains_both_labels(session_id):
    cases = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/cases/").json()

    assert any(c["malicious"] for c in cases)
    assert any(not c["malicious"] for c in cases), (
        "정상 케이스가 없으면 전부 차단하는 룰이 만점을 받는다."
    )


def test_detections_carry_case_markers(session_id, score):
    """마커가 하나도 실리지 않으면 대응 자체가 불가능하다."""
    detections = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/detections/"
    ).json()

    assert detections, "경보가 한 건도 수집되지 않았다."
    assert any(d["marker"] for d in detections), (
        "어느 경보도 X-FSL-Case 를 싣고 있지 않다. "
        "deploy/suricata/suricata.yaml 의 eve-log http dump-all-headers 설정을 확인하라."
    )


def test_both_engines_produce_detections(session_id, score):
    """Suricata 와 ModSecurity 가 둘 다 살아 있어야 한다."""
    detections = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/detections/"
    ).json()

    assert {d["source"] for d in detections} == {"suricata", "modsecurity"}


def test_criterion_3_true_positive_is_not_zero(score):
    """완료 기준 3-a: 탐지되는 공격이 존재한다. 이게 0이면 가설이 깨진다."""
    assert score["tp"] > 0, f"공격이 하나도 탐지되지 않았다. 스코어: {score}"


def test_criterion_3_true_negative_is_not_zero(score):
    """완료 기준 3-b: 조용히 지나가는 정상 트래픽이 존재한다."""
    assert score["tn"] > 0, (
        f"정상 트래픽이 전부 경보를 일으켰다. 오탐 채점이 무의미하다. 스코어: {score}"
    )


def test_score_has_no_pipeline_warnings(score):
    """파이프라인 고장 경고가 없어야 점수를 믿을 수 있다."""
    pipeline_warnings = [
        w for w in score["warnings"] if "marker" in w or "source_ip" in w
    ]

    assert not pipeline_warnings, pipeline_warnings


def test_detections_are_spread_across_cases(session_id, score):
    """keep-alive 에서 한 흐름의 경보가 첫 케이스로 몰리지 않아야 한다."""
    owners = [len(c["detection_ids"]) for c in score["per_case"] if c["detected"]]

    assert len(owners) > 1, (
        f"탐지된 케이스가 하나뿐이다. 경보가 한 케이스로 몰렸을 수 있다. "
        f"스코어: {score}"
    )


def test_criterion_4_adding_a_rule_moves_the_score():
    """완료 기준 4: 룰을 추가하면 다음 판의 점수가 예측한 방향으로 움직인다.

    '정상 검색'에만 걸리는 룰을 넣으면 오탐이 늘어야 한다.
    """
    original = requests.get(f"{PLATFORM_URL}/api/rules/").json()["content"]

    try:
        applied = requests.post(
            f"{PLATFORM_URL}/api/rules/apply/",
            json={"content": original + NOISY_RULE},
            timeout=120,
        )
        assert applied.ok, applied.text

        after = score_when_ready(run_redteam(), until=lambda s: s["fp"] > 0)
        assert after["fp"] > 0, (
            f"'apple' 을 때리는 룰을 넣었는데 오탐이 잡히지 않았다. 스코어: {after}"
        )
    finally:
        requests.post(
            f"{PLATFORM_URL}/api/rules/apply/", json={"content": original}, timeout=120
        )


def test_invalid_rule_is_rejected_and_not_applied():
    """검증을 통과하지 못한 룰은 파일에 쓰이지 않는다."""
    before = requests.get(f"{PLATFORM_URL}/api/rules/").json()["content"]

    response = requests.post(
        f"{PLATFORM_URL}/api/rules/apply/",
        json={"content": "이건 룰이 아니다"},
        timeout=120,
    )

    assert response.status_code == 400
    assert requests.get(f"{PLATFORM_URL}/api/rules/").json()["content"] == before
