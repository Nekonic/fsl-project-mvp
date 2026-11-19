from datetime import datetime, timedelta, timezone

import pytest

from domain.scoring.correlate import correlate
from domain.types import ActionRecord, CaseRecord, DetectionRecord

T0 = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)


def case(case_id="c1", malicious=True, correlation="marker", marker=None, source_ip=None, start=0, end=5):
    return CaseRecord(
        case_id=case_id,
        name=case_id,
        malicious=malicious,
        correlation=correlation,
        marker=marker if marker is not None else case_id,
        source_ip=source_ip,
        started_at=T0 + timedelta(seconds=start),
        ended_at=T0 + timedelta(seconds=end),
    )


def det(detection_id="d1", marker=None, src_ip=None, at=1):
    return DetectionRecord(detection_id=detection_id, timestamp=T0 + timedelta(seconds=at), src_ip=src_ip, marker=marker)


def test_marker_case_matches_detection_with_same_marker():
    result = correlate([case()], [det(marker="c1")])

    assert result.matches[0].detected is True
    assert result.matches[0].detection_ids == ("d1",)
    assert result.unmatched_detection_ids == ()


def test_the_marker_comes_from_the_action_not_the_case_id():
    action = ActionRecord(
        action_id="a7", kind="request", marker="m-a7", correlation="marker", source_ip="10.0.0.1",
        started_at=T0, ended_at=T0 + timedelta(seconds=1),
    )

    result = correlate([action.as_case()], [det("hit", marker="m-a7"), det("miss", marker="a7")])

    assert result.matches[0].detection_ids == ("hit",)
    assert result.matches[0].malicious is None


def test_marker_case_ignores_time_and_ip():
    result = correlate([case(source_ip="10.0.0.1")], [det(marker="c1", src_ip="10.0.0.9", at=9999)])

    assert result.matches[0].detected is True


def test_window_case_matches_on_ip_and_time():
    result = correlate([case(correlation="window", source_ip="10.0.0.1")], [det(src_ip="10.0.0.1", at=3)])

    assert result.matches[0].detected is True


def test_a_window_case_leaves_a_record_another_request_s_marker_names_to_that_request():
    result = correlate(
        [case(correlation="window", source_ip="10.0.0.1")],
        [det("own", src_ip="10.0.0.1", at=3), det("labelled", marker="c1", src_ip="10.0.0.1", at=3),
         det("sqlmap", marker="another-case", src_ip="10.0.0.1", at=4)],
    )

    assert result.matches[0].detection_ids == ("own", "labelled")


def test_window_case_rejects_different_ip():
    result = correlate([case(correlation="window", source_ip="10.0.0.1")], [det(src_ip="10.0.0.2", at=3)])

    assert result.matches[0].detected is False


def test_window_slack_is_two_seconds_on_either_side():
    result = correlate(
        [case(correlation="window", source_ip="10.0.0.1", start=0, end=5)],
        [det("edge", src_ip="10.0.0.1", at=-2), det("late-edge", src_ip="10.0.0.1", at=7),
         det("too-early", src_ip="10.0.0.1", at=-2.001), det("too-late", src_ip="10.0.0.1", at=7.001)],
    )

    assert result.matches[0].detection_ids == ("edge", "late-edge")
    assert result.unmatched_detection_ids == ("too-early", "too-late")


def test_window_case_never_matches_by_marker_and_marker_case_never_by_window():
    assert correlate([case(correlation="window", source_ip="10.0.0.1")],
                     [det(marker="c1", src_ip="10.0.0.9", at=3)]).matches[0].detected is False
    assert correlate([case(source_ip="10.0.0.1")],
                     [det(src_ip="10.0.0.1", at=3)]).matches[0].detected is False


def test_many_alerts_collapse_into_one_case():
    result = correlate([case()], [det("d1", marker="c1"), det("d2", marker="c1")])

    assert len(result.matches) == 1
    assert result.matches[0].detection_ids == ("d1", "d2")


def test_a_forced_strategy_overrides_every_case():
    cases = [case(source_ip="10.0.0.1")]
    detections = [det(src_ip="10.0.0.1", at=3)]

    assert correlate(cases, detections).matches[0].detected is False
    assert correlate(cases, detections, strategy="window").matches[0].detected is True


def test_an_unknown_strategy_is_refused():
    with pytest.raises(ValueError):
        correlate([case(correlation="psychic")], [])
    with pytest.raises(ValueError):
        correlate([case()], [], strategy="psychic")


def test_warnings_name_missing_markers_and_missing_source_ips():
    assert ("no_marker",) in correlate([case()], [det(src_ip="10.0.0.1")]).warnings
    assert correlate([case()], []).warnings == ()
    assert any(w[0] == "no_source_ip" for w in correlate([case(correlation="window")], []).warnings)
