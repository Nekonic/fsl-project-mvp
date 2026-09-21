from datetime import datetime, timedelta, timezone

import pytest

from scoring.correlate import WINDOW_SLACK, correlate
from scoring.types import CaseRecord, DetectionRecord

T0 = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)

def case(
    case_id="c1",
    name="n",
    malicious=True,
    correlation="marker",
    source_ip=None,
    start=0,
    end=5,
):
    return CaseRecord(
        case_id=case_id,
        name=name,
        malicious=malicious,
        correlation=correlation,
        source_ip=source_ip,
        started_at=T0 + timedelta(seconds=start),
        ended_at=T0 + timedelta(seconds=end),
    )

def det(detection_id="d1", marker=None, src_ip=None, at=1, source="suricata"):
    return DetectionRecord(
        detection_id=detection_id,
        source=source,
        signature="sig",
        timestamp=T0 + timedelta(seconds=at),
        src_ip=src_ip,
        marker=marker,
    )

def test_window_slack_is_two_seconds():
    assert WINDOW_SLACK == timedelta(seconds=2)

def test_marker_case_matches_detection_with_same_marker():
    result = correlate([case(case_id="c1")], [det(detection_id="d1", marker="c1")])

    assert len(result.matches) == 1
    assert result.matches[0].detected is True
    assert result.matches[0].detection_ids == ("d1",)
    assert result.unmatched_detection_ids == ()

def test_marker_case_without_matching_marker_is_undetected():
    result = correlate([case(case_id="c1")], [det(detection_id="d1", marker="other")])

    assert result.matches[0].detected is False
    assert result.matches[0].detection_ids == ()
    assert result.unmatched_detection_ids == ("d1",)

def test_marker_case_ignores_time_and_ip():
                                                                         
    result = correlate(
        [case(case_id="c1", source_ip="10.0.0.1")],
        [det(detection_id="d1", marker="c1", src_ip="10.0.0.9", at=9999)],
    )

    assert result.matches[0].detected is True

def test_window_case_matches_on_ip_and_time():
    result = correlate(
        [case(correlation="window", source_ip="10.0.0.1", start=0, end=5)],
        [det(src_ip="10.0.0.1", at=3)],
    )

    assert result.matches[0].detected is True

def test_window_case_rejects_different_ip():
    result = correlate(
        [case(correlation="window", source_ip="10.0.0.1", start=0, end=5)],
        [det(src_ip="10.0.0.2", at=3)],
    )

    assert result.matches[0].detected is False

def test_window_case_accepts_detection_within_slack():
    result = correlate(
        [case(correlation="window", source_ip="10.0.0.1", start=0, end=5)],
        [det(detection_id="early", src_ip="10.0.0.1", at=-2),
         det(detection_id="late", src_ip="10.0.0.1", at=7)],
    )

    assert set(result.matches[0].detection_ids) == {"early", "late"}

def test_window_case_rejects_detection_outside_slack():
    result = correlate(
        [case(correlation="window", source_ip="10.0.0.1", start=0, end=5)],
        [det(src_ip="10.0.0.1", at=8)],
    )

    assert result.matches[0].detected is False

def test_window_case_never_matches_by_marker():
                                                                            
    result = correlate(
        [case(case_id="c1", correlation="window", source_ip="10.0.0.1", start=0, end=5)],
        [det(marker="c1", src_ip="10.0.0.9", at=3)],
    )

    assert result.matches[0].detected is False

def test_marker_case_never_matches_by_window():
    result = correlate(
        [case(case_id="c1", correlation="marker", source_ip="10.0.0.1", start=0, end=5)],
        [det(marker=None, src_ip="10.0.0.1", at=3)],
    )

    assert result.matches[0].detected is False

def test_multiple_detections_collapse_to_one_case():
    result = correlate(
        [case(case_id="c1")],
        [det(detection_id="d1", marker="c1"), det(detection_id="d2", marker="c1")],
    )

    assert len(result.matches) == 1
    assert result.matches[0].detection_ids == ("d1", "d2")

def test_warns_when_no_detection_carries_a_marker():
    result = correlate([case(case_id="c1")], [det(marker=None, src_ip="10.0.0.1")])

    assert any("marker" in w for w in result.warnings)

def test_no_marker_warning_when_there_are_no_detections_at_all():
                                                                         
    result = correlate([case(case_id="c1")], [])

    assert result.warnings == ()

def test_warns_when_window_case_has_no_source_ip():
    result = correlate([case(correlation="window", source_ip=None)], [])

    assert any("source_ip" in w for w in result.warnings)

def test_rejects_unknown_correlation_strategy():
    with pytest.raises(ValueError, match="correlation"):
        correlate([case(correlation="fuzzy")], [])

def test_empty_inputs_produce_empty_result():
    result = correlate([], [])

    assert result.matches == ()
    assert result.unmatched_detection_ids == ()
    assert result.warnings == ()
